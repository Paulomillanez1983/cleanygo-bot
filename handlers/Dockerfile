# ====== Base Nixpacks ======
FROM ghcr.io/railwayapp/nixpacks:ubuntu-1745885067

WORKDIR /app

# Copiar nixpkgs si existe
COPY .nixpacks/nixpkgs-*.nix .nixpacks/

# Instalar dependencias del sistema
RUN nix-env -if .nixpacks/nixpkgs-*.nix && nix-collect-garbage -d

# Copiar código
COPY . /app

# Crear virtualenv y cachear pip
RUN python -m venv --copies /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# Añadir venv al PATH
ENV PATH="/opt/venv/bin:$PATH"

# Añadir carpeta app al PYTHONPATH para que services y handlers se reconozcan como paquetes
ENV PYTHONPATH="/app:$PYTHONPATH"

# Comando final con Gunicorn
CMD ["gunicorn", "-w", "1", "-k", "gevent", "--bind", "0.0.0.0:$PORT", "bot:app", "--log-level", "info", "--access-logfile", "-", "--error-logfile", "-"]
