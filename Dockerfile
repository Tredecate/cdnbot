FROM python:3.14-slim

ARG PYTHONUNBUFFERED=1
ARG PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["python"]
CMD ["app.py"]