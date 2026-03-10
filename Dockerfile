# ==============================
# CleanyGo Bot - Dockerfile
# Railway + Nixpacks compatible
# ==============================

# ===== Base Nixpacks =====
FROM ghcr.io/railwayapp/nixpacks:ubuntu-1745885067

# ====================
# 1. Directorio base
# ====================
WORKDIR /app

# ====================
# 2. Copiar nixpkgs si existe
# ====================
# Esto es opcional. No rompe si no existe.
COPY .nixpacks/ .nixpacks/

# ====================
# 3. Instalar dependencias del sistema
# ====================
RUN if ls .nixpacks/nixpkgs-*.nix 1> /dev/null 2>&1; then \
        nix-env -if .nixpacks/nixpkgs-*.nix ; \
        nix-collect-garbage -d ; \
    fi

# ====================
# 4. Copiar código fuente
# ====================
COPY . .

# ====================
# 5. Crear entorno virtual
# ====================
RUN python -m venv /opt/venv

# ====================
# 6. Activar venv en PATH
# ====================
ENV PATH="/opt/venv/bin:$PATH"

# ====================
# 7. Instalar dependencias Python
# ====================
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ====================
# 8. PYTHONPATH para imports internos
# ====================
ENV PYTHONPATH="/app"

# ====================
# 9. Puerto Railway
# ====================
EXPOSE 8080

# ====================
# 10. Run con Gunicorn
# ====================
CMD ["sh", "-c", "gunicorn -w 1 -k gevent --bind 0.0.0.0:${PORT:-8080} main:app --log-level info --access-logfile - --error-logfile -"]
