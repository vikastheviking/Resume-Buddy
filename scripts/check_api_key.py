"""
Standalone API Key Tester & Diagnostics Tool.
Use this script to test any API key (DeepSeek, NVIDIA NIM, Groq, or OpenAI)
and see the exact response status, latency, and error details.

Usage:
  python scripts/check_api_key.py
  (or pass your key as an argument: python scripts/check_api_key.py YOUR_API_KEY)
"""

import sys
import time
import requests

ENDPOINTS = {
    "1": {
        "name": "DeepSeek Official API",
        "url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat"
    },
    "2": {
        "name": "NVIDIA NIM",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "model": "deepseek-ai/deepseek-r1"
    },
    "3": {
        "name": "Groq Cloud",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile"
    },
    "4": {
        "name": "SiliconFlow (DeepSeek host)",
        "url": "https://api.siliconflow.cn/v1/chat/completions",
        "model": "deepseek-ai/DeepSeek-V3"
    }
}


def test_api_key(api_key: str, endpoint_choice: str = "1", custom_url: str = None, custom_model: str = None):
    cfg = ENDPOINTS.get(endpoint_choice, ENDPOINTS["1"])
    url = custom_url or cfg["url"]
    model = custom_model or cfg["model"]
    provider_name = cfg["name"]

    print(f"\n==========================================")
    print(f"Testing API Key on: {provider_name}")
    print(f"Target URL:         {url}")
    print(f"Model ID:           {model}")
    print(f"Key Prefix:         {api_key[:8]}... (hidden)")
    print(f"==========================================\n")
    print("Sending ping request...")

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Respond with the word 'PONG' and nothing else."}],
        "max_tokens": 10,
        "temperature": 0.0
    }

    start_time = time.time()
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        latency = round(time.time() - start_time, 2)

        print(f"HTTP Status Code:   {response.status_code}")
        print(f"Response Latency:   {latency} seconds\n")

        if response.status_code == 200:
            data = response.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            print("------------------------------------------")
            print("SUCCESS! Your API Key is ACTIVE and WORKING.")
            print(f"Model Reply: '{reply}'")
            print("------------------------------------------")
            return True
        elif response.status_code == 401:
            print("------------------------------------------")
            print("FAILED: 401 Unauthorized (Invalid API Key).")
            print("Reason: The server rejected this key. Check that you copied the complete key without spaces.")
            print(f"Server Response: {response.text}")
            print("------------------------------------------")
        elif response.status_code == 404:
            print("------------------------------------------")
            print("FAILED: 404 Not Found (Invalid Model or Endpoint).")
            print(f"Reason: The model '{model}' does not exist on this endpoint.")
            print(f"Server Response: {response.text}")
            print("------------------------------------------")
        elif response.status_code == 429:
            print("------------------------------------------")
            print("FAILED: 429 Rate Limited or Out of Credits.")
            print("Reason: You have exceeded your free tier rate limit or quota.")
            print(f"Server Response: {response.text}")
            print("------------------------------------------")
        else:
            print(f"FAILED: HTTP {response.status_code}")
            print(f"Server Response: {response.text}")

    except requests.exceptions.Timeout:
        print("------------------------------------------")
        print("FAILED: Connection Timed Out (>15s).")
        print("Reason: The remote server did not respond within 15 seconds. The endpoint may be down or slow.")
        print("------------------------------------------")
    except Exception as e:
        print(f"FAILED: Connection Error: {str(e)}")

    return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        key = sys.argv[1]
        choice = sys.argv[2] if len(sys.argv) > 2 else "1"
        test_api_key(key, choice)
    else:
        print("--- API Key Diagnostics ---")
        print("Select Provider to test:")
        for k, v in ENDPOINTS.items():
            print(f"  [{k}] {v['name']} ({v['model']})")
        
        choice = input("\nEnter choice (1-4) [default: 1]: ").strip() or "1"
        key = input("Enter your API Key: ").strip()
        
        if not key:
            print("No key entered. Exiting.")
            sys.exit(1)
            
        test_api_key(key, choice)
