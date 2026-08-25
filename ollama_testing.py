import json
from ollama import Client

# ==========================================
# CONFIGURATION
# ==========================================
# Replace this with the actual IP address of your Windows Server
REMOTE_SERVER_IP = "192.168.1.39" 
OLLAMA_PORT = "11434"

# Set up the remote client
remote_url = f"http://{REMOTE_SERVER_IP}:{OLLAMA_PORT}"
client = Client(host=remote_url)


def check_models():
    """Fetches and displays a list of models currently installed on the remote server."""
    print(f"\n[1] Connecting to remote Ollama server at {remote_url}...")
    try:
        response = client.list()
        models = response.get('models', [])
        
        if not models:
            print(" -> Connection successful, but NO models are currently installed on the server.")
            return []
            
        print(" -> Connection successful! Found the following models:")
        model_names = []
        for model in models:
            size_in_gb = model.get('size', 0) / (1024 ** 3)
            # Use 'model' as fallback if 'name' is not present
            name = model.get('name', model.get('model', 'Unknown'))
            print(f"    - {name} ({size_in_gb:.2f} GB)")
            model_names.append(name)
            
        return model_names
        
    except Exception as e:
        print(f" -> ERROR: Failed to connect. Is the IP correct and the firewall open on the server?\nDetails: {e}")
        return []


def query_model(model_name: str, prompt: str):
    """Sends a prompt to the specified model on the remote server and saves the response."""
    print(f"\n[2] Sending request to model '{model_name}' on the remote server...")
    try:
        response = client.chat(
            model=model_name,
            messages=[{'role': 'user', 'content': prompt}]
        )
        
        answer = response['message']['content']
        print("\n--- Received Response ---")
        print(answer)
        print("-------------------------\n")
        
        # Save to local file
        save_response(model_name, prompt, answer)
        
    except Exception as e:
        print(f" -> ERROR: Request failed. Details: {e}")


def save_response(model_name: str, prompt: str, answer: str):
    """Saves the prompt and response to a local JSON file."""
    data = {
        "model": model_name,
        "prompt": prompt,
        "response": answer
    }
    
    file_name = "remote_responses_log.json"
    with open(file_name, "a") as f:
        f.write(json.dumps(data) + "\n")
    print(f"[Success] Response securely saved to local file: {file_name}")


if __name__ == "__main__":
    print("=== OLLAMA REMOTE CONNECTION TEST ===")
    
    # 1. Check available models
    available_models = check_models()
    
    # Filter out embedding models because they don't support chat
    chat_models = [m for m in available_models if "embed" not in m.lower()]
    
    # 2. If models exist, pick the first one and send a test query
    if chat_models:
        first_model = chat_models[1] # Automatically pick the first available model
        test_prompt = "Say about Gramosoft technoloagy"
        
        query_model(first_model, test_prompt)
    else:
        print("\n[!] Please pull a chat model on the Windows server first (e.g., 'ollama pull llama3')")