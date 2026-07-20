FROM python:3.11-slim

WORKDIR /app

# Copy the requirements file into the image container
COPY requirements.txt .

# Install dependencies system-wide to guarantee global PATH accessibility 
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Copy the rest of your app code
COPY . .

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]