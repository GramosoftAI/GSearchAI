from openai import OpenAI

API_BASE_URL = "http://103.191.132.28:7218/v1"
API_KEY = "gsai_prod_9d4b7c6f2e8a1c5f7b9d3a6e4f8c2b1a7d5e9f3c6a8b2d4e1f7c9a5b3e6d8f2"  # Use dummy string if no key is enforced
MODEL_NAME = "qwen2.5:14b"  # Updated to match server catalog

def test_server_connection():
    try:
        client = OpenAI(
            base_url=API_BASE_URL,
            api_key=API_KEY
        )

        print(f"Connecting to server at {API_BASE_URL}...")
        print(f"Testing model: {MODEL_NAME}\n")

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "user", "content": "Hello! Please reply with 'Connected successfully'."}
            ],
            max_tokens=20
        )

        print("✅ Connection Successful!")
        print(f"Server Response: {response.choices[0].message.content.strip()}")

    except Exception as e:
        print("❌ Connection Failed!")
        print(f"Error details: {e}")

if __name__ == "__main__":
    test_server_connection()