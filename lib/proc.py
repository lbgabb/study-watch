"""进程命令行查询：纯 ctypes 走 NtQueryInformationProcess 读 PEB。

为什么不用 PowerShell/WMI：
  - 每次查询要起一个进程，几十毫秒到几百毫秒，仪表盘 5 秒轮询一次不划算
  - 换台机器不一定有 PowerShell / WMIC（后者在新 Windows 上已弃用）
  - 沙箱环境常禁止起子进程，纯内存读取没有这个问题

原理：NtQueryInformationProcess(ProcessBasicInformation) 拿到 PEB 地址，
      PEB->ProcessParameters->CommandLine 就是完整命令行（UNICODE_STRING）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

ntdll = ctypes.WinDLL("ntdll")
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010

PROCESS_BASIC_INFORMATION_CLASS = 0


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wt.USHORT), ("MaximumLength", wt.USHORT),
                ("Buffer", ctypes.c_void_p)]


class _PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("ExitStatus", ctypes.c_long), ("PebBaseAddress", ctypes.c_void_p),
                ("AffinityMask", ctypes.c_void_p), ("BasePriority", ctypes.c_long),
                ("UniqueProcessId", ctypes.c_void_p),
                ("InheritedFromUniqueProcessId", ctypes.c_void_p)]


class _CURDIR(ctypes.Structure):
    _fields_ = [("DosPath", _UNICODE_STRING), ("Handle", ctypes.c_void_p)]


class _RTL_USER_PROCESS_PARAMETERS(ctypes.Structure):
    _fields_ = [("MaximumLength", wt.ULONG), ("Length", wt.ULONG), ("Flags", wt.ULONG),
                ("DebugFlags", wt.ULONG), ("ConsoleHandle", ctypes.c_void_p),
                ("ConsoleFlags", wt.ULONG), ("StandardInput", ctypes.c_void_p),
                ("StandardOutput", ctypes.c_void_p), ("StandardError", ctypes.c_void_p),
                ("CurrentDirectory", _CURDIR), ("DllPath", _UNICODE_STRING),
                ("ImagePathName", _UNICODE_STRING), ("CommandLine", _UNICODE_STRING)]


def _open(pid: int) -> int | None:
    for access in (PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
                   PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ):
        h = kernel32.OpenProcess(access, False, pid)
        if h:
            return h
    return None


def command_line(pid: int) -> str:
    """返回进程完整命令行；拿不到就返回空字符串（无异常）。"""
    handle = _open(pid)
    if not handle:
        return ""
    try:
        pbi = _PROCESS_BASIC_INFORMATION()
        status = ntdll.NtQueryInformationProcess(
            handle, PROCESS_BASIC_INFORMATION_CLASS, ctypes.byref(pbi),
            ctypes.sizeof(pbi), None)
        if status != 0 or not pbi.PebBaseAddress:
            return ""

        # PEB->ProcessParameters 在 64 位下偏移 0x20
        params_ptr = ctypes.c_void_p()
        if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(pbi.PebBaseAddress + 0x20),
                                          ctypes.byref(params_ptr),
                                          ctypes.sizeof(params_ptr), None):
            return ""
        if not params_ptr:
            return ""

        params = _RTL_USER_PROCESS_PARAMETERS()
        if not kernel32.ReadProcessMemory(handle, params_ptr, ctypes.byref(params),
                                          ctypes.sizeof(params), None):
            return ""
        us = params.CommandLine
        if not us.Buffer or not us.Length:
            return ""

        buf = ctypes.create_unicode_buffer(us.Length // 2 + 1)
        if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(us.Buffer), buf,
                                          us.Length, None):
            return ""
        return buf.value
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(handle)


def pids_matching(needle: str, names: tuple[str, ...] = ("python.exe", "pythonw.exe")) -> list[int]:
    """列出命令行里含 needle 的 python 进程。

    用 CreateToolhelp32Snapshot 枚举进程（纯 API，不起子进程）。
    """
    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                    ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", ctypes.c_char * MAX_PATH)]

    out: list[int] = []
    try:
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1:
            return out
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            ok = kernel32.Process32First(snap, ctypes.byref(entry))
            while ok:
                exe = entry.szExeFile.decode("mbcs", errors="ignore").lower()
                if exe in names:
                    pid = int(entry.th32ProcessID)
                    if needle.lower() in command_line(pid).lower():
                        out.append(pid)
                ok = kernel32.Process32Next(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)
    except Exception:
        return out
    return sorted(out)


if __name__ == "__main__":   # 手动自测：python lib/proc.py
    import time

    t0 = time.perf_counter()
    pids = pids_matching("monitor.py")
    dt = (time.perf_counter() - t0) * 1000
    print(f"命令行含 monitor.py 的进程：{pids}（耗时 {dt:.1f} ms）")
    print(f"本进程命令行：{command_line(kernel32.GetCurrentProcessId())[:120]}")
