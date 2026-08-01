FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py database.py keyboards.py main.py ./
COPY auth_server.py auth_bridge.py start.sh ./
COPY handlers/ handlers/
COPY services/ services/

RUN chmod +x start.sh

CMD ["./start.sh"]
