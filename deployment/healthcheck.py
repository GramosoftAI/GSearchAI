import urllib.request
import urllib.error
import sys
import time

def check_health():
    url = "http://localhost:4915/docs" # Assuming docs as a stand-in for /health for now
    max_retries = 5
    for i in range(max_retries):
        try:
            response = urllib.request.urlopen(url, timeout=5)
            if response.status == 200:
                print("Health check passed.")
                return True
        except urllib.error.URLError as e:
            print(f"Health check failed (attempt {i+1}/{max_retries}): {e}")
        time.sleep(2)
    return False

if __name__ == "__main__":
    if not check_health():
        sys.exit(1)
    sys.exit(0)
