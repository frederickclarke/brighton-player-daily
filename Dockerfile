# Dockerfile

# 1. Use an official Python runtime as a parent image.
# We use a "slim" version which is smaller and more secure.
FROM python:3.11-slim

# 2. Set the working directory inside the container.
# All subsequent commands will run from this path.
WORKDIR /app

# 3. Set environment variables to prevent Python from writing .pyc files.
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 4. Copy the requirements file into the container.
# This is done first to take advantage of Docker's layer caching.
# If the requirements don't change, Docker won't need to reinstall them on every build.
COPY requirements.txt .

# 5. Install the Python dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy the rest of your application's code into the container.
# This includes app.py, your templates folder, and your CSV file.
COPY . .

# 7. Expose a port. Gunicorn will run on this port inside the container.
# Fly.io will automatically map public traffic on ports 80 (HTTP) and 443 (HTTPS) to this internal port.
EXPOSE 8080

# 8. Define the command to run your application.
# This tells the container to start the Gunicorn server, listening on all network interfaces
# on the port we exposed, and to serve the 'app' object from your 'app.py' file.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]