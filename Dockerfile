FROM python:3.12-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Flask app
COPY flask_webhook.py .

# Expose the Flask port
EXPOSE 5000

# Start the Flask app
CMD ["python", "flask_webhook.py"]
