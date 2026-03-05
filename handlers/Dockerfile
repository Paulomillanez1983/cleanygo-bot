# ====== Stage 0: Base Nixpacks ======
FROM ghcr.io/railwayapp/nixpacks:ubuntu-1745885067

# Directorio de trabajo
WORKDIR /app

# Copiar definición de nixpkgs (si la tenés)
COPY .nixpacks/nixpkgs-*.nix .nixpacks/

# Instalar dependencias del sistema (Python y GCC)
RUN nix-env -if .nixpacks/nixpkgs-*.nix && nix-collect-garbage -d

# Copiar todo el código
COPY . /app

# Crear virtualenv y cachear pip
RUN python -m venv --copies /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

# Añadir venv al PATH
RUN printf '\nPATH=/opt/venv/bin:$PATH' >> /root/.profile

# Comando final con Gunicorn
CMD ["gunicorn", "-w", "4", "-k", "gevent", "--bind", "0.0.0.0:$PORT", "bot:app", "--log-level", "info", "--access-logfile", "-", "--error-logfile", "-"]
