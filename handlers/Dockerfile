# ====== Base Nixpacks ======
FROM ghcr.io/railwayapp/nixpacks:ubuntu-1745885067

# ==================== 1. Directorio de trabajo ====================
WORKDIR /app

# ==================== 2. Copiar nixpkgs si existe ====================
COPY .nixpacks/nixpkgs-*.nix .nixpacks/

# ==================== 3. Instalar dependencias del sistema ====================
RUN nix-env -if .nixpacks/nixpkgs-*.nix && nix-collect-garbage -d

# ==================== 4. Copiar todo el código ====================
COPY . /app

# ==================== 5. Crear virtualenv y cachear pip ====================
RUN python -m venv --copies /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# ==================== 6. Añadir venv al PATH ====================
ENV PATH="/opt/venv/bin:$PATH"

# ==================== 7. Añadir app al PYTHONPATH ====================
# Para que services y handlers se reconozcan como paquetes
ENV PYTHONPATH="/app:$PYTHONPATH"

# ==================== 8. Comando final con Gunicorn ====================
# Levanta main:app (main.py importa bot.app)
# 1 worker con gevent es suficiente para Telegram
CMD ["gunicorn", "-w", "1", "-k", "gevent", "--bind", "0.0.0.0:$PORT", "main:app", "--log-level", "info", "--access-logfile", "-", "--error-logfile", "-"]
