FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
# When running on platforms like Render the PORT environment variable is
# automatically injected. Bind to it if available, otherwise fall back
# to the usual 8000. We wrap the command in `sh -c` because the
# `${PORT:-8000}` substitution is performed by the shell.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]