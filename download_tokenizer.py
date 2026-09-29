import os
import urllib.request

models_dir = os.path.join(os.path.dirname(__file__), 'models')
os.makedirs(models_dir, exist_ok=True)
tokenizer_path = os.path.join(models_dir, 'tokenizer.json')

if not os.path.exists(tokenizer_path):
    print("Downloading tokenizer.json...")
    url = "https://huggingface.co/BAAI/bge-large-en-v1.5/resolve/main/tokenizer.json"
    urllib.request.urlretrieve(url, tokenizer_path)
    print("Downloaded.")
else:
    print("tokenizer.json already exists.")
