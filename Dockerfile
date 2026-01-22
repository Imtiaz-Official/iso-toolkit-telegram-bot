FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code (both files, run bot_with_iso.py)
COPY bot.py .
COPY bot_with_iso.py .

# Create non-root user for security
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app
USER botuser

# Run the bot with ISO hosting support
CMD ["python", "bot_with_iso.py"]
