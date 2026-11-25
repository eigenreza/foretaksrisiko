# Streamlit demo image for Azure App Service (Linux). The image holds the package, the public
# demo data, the figures and the pinned app requirements. No registers or lakehouse are reached.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /srv

COPY app/requirements.txt /srv/app/requirements.txt
RUN pip install -r /srv/app/requirements.txt

COPY pyproject.toml README.md LICENSE /srv/
COPY src /srv/src
COPY configs /srv/configs
RUN pip install --no-deps /srv

COPY app /srv/app
COPY demo_data /srv/demo_data
COPY figures /srv/figures
COPY .streamlit /srv/.streamlit

# The app runs as an ordinary user, not as root.
RUN useradd --create-home --uid 1000 app && chown -R app:app /srv
USER app

EXPOSE 8000
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=8000", "--server.address=0.0.0.0"]
