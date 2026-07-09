import json
import urllib.request

BASE_URL = "http://127.0.0.1:8012/v1"
MODEL = "Qwen3-1.7B"

url = f"{BASE_URL}/chat/completions"

payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "你好，用一句中文回复我。"}],
    "temperature": 0.2,
    "max_tokens": 128,
}

req = urllib.request.Request(
    url=url,
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer EMPTY",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(data["choices"][0]["message"]["content"])
except Exception as e:
    print("请求失败：", repr(e))
