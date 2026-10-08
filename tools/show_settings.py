"""查看设置接口当前暴露的内容（只读、不修改任何东西）。"""
import json
import sys
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
d = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/config", timeout=20).read())
v = d["values"]

print(f"可编辑项 {len(v)} 个｜截图规则 {d['rules_count']} 条")
print(f"配置文件：{d['config_path']}")
key = d["key"]
print(f"API key：{key['masked'] or '（未配置）'}  来源：{key['source'] or '无'}  环境变量名：{key['env_name']}")
print()
print("当前生效值：")
for k in ("interval_sec", "idle_skip_sec", "capture.min_gap_sec", "detail", "jpeg_quality",
          "max_width", "judge.strictness", "reminder.enabled", "reminder.sound",
          "reminder.off_task_streak_required", "privacy.save_shots", "privacy.save_api_raw"):
    print(f"  {k:<34} = {v.get(k)}")
print(f"  {'api.model':<34} = {v.get('api.model')}")
print(f"  {'api.base_url':<34} = {v.get('api.base_url')}")
print(f"  {'judge.goal':<34} = {str(v.get('judge.goal'))[:40]}")
print()
print("改了需要重启监督的项：", "、".join(d["restart_keys"].values()))
