#!/usr/bin/env python3
"""Construye Rumbo 11 v1.0.0 a partir del ZIP oficial de la Fase 9.

Uso:
    python finalize_phase10.py Rumbo11_Fase_9_v0.9.0.zip

El script no modifica el ZIP de entrada. Extrae una copia, incorpora los archivos
finales de instalación y entrega, ejecuta verificaciones estáticas y crea:
    Rumbo11_Final_v1.0.0.zip
    Rumbo11_Final_v1.0.0.sha256
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import textwrap
import zipfile
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.0"
PRODUCT = "Rumbo 11"
FINAL_ZIP = "Rumbo11_Final_v1.0.0.zip"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8", newline="\n")


def find_root(base: Path) -> Path:
    candidates = [p.parent for p in base.rglob("manage.py")]
    if not candidates:
        raise RuntimeError("El ZIP no contiene manage.py.")
    candidates.sort(key=lambda p: len(p.parts))
    return candidates[0]


def append_once(path: Path, marker: str, content: str) -> None:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker not in current:
        write(path, current.rstrip() + "\n\n" + textwrap.dedent(content).strip() + "\n")


def create_runtime(root: Path) -> None:
    write(root / "VERSION", VERSION + "\n")

    requirements = root / "requirements.txt"
    req_text = requirements.read_text(encoding="utf-8") if requirements.exists() else ""
    required = {
        "Django": "Django==5.2.16",
        "waitress": "waitress==3.0.2",
        "openpyxl": "openpyxl==3.1.5",
        "Pillow": "Pillow==11.3.0",
        "coverage": "coverage==7.10.3",
    }
    lines = [line.rstrip() for line in req_text.splitlines() if line.strip()]
    lower = "\n".join(lines).lower()
    for package, pinned in required.items():
        if not re.search(rf"(?mi)^\s*{re.escape(package.lower())}\s*[=<>]", lower):
            lines.append(pinned)
    write(requirements, "\n".join(lines) + "\n")
    write(root / "requirements.lock", "\n".join(lines) + "\n")

    env_example = root / ".env.example"
    append_once(env_example, "RUMBO11_PORT=8000", """
        # Configuración local definitiva
        RUMBO11_PORT=8000
        RUMBO11_HOST=127.0.0.1
        RUMBO11_HTTPS_ENABLED=false
        SESSION_IDLE_TIMEOUT_SECONDS=1800
        SESSION_ABSOLUTE_TIMEOUT_SECONDS=28800
        LOGIN_MAX_FAILED_ATTEMPTS=5
        LOGIN_LOCKOUT_MINUTES=15
    """)

    write(root / "run_local.py", r'''
        from __future__ import annotations

        import os
        import socket
        import sys
        import threading
        import time
        import webbrowser
        from pathlib import Path

        BASE_DIR = Path(__file__).resolve().parent
        os.chdir(BASE_DIR)
        sys.path.insert(0, str(BASE_DIR))
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

        def load_env() -> None:
            env_path = BASE_DIR / ".env"
            if not env_path.exists():
                return
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

        def port_available(host: str, port: int) -> bool:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                return sock.connect_ex((host, port)) != 0

        def choose_port(host: str, preferred: int) -> int:
            for port in range(preferred, preferred + 20):
                if port_available(host, port):
                    return port
            raise RuntimeError("No se encontró un puerto disponible entre %s y %s." % (preferred, preferred + 19))

        def open_browser(url: str) -> None:
            time.sleep(1.25)
            try:
                webbrowser.open(url, new=2)
            except Exception:
                pass

        def main() -> int:
            load_env()
            try:
                import django
                django.setup()
                from django.core.management import call_command
                from waitress import serve
                from config.wsgi import application
            except Exception as exc:
                print("[ERROR] No fue posible cargar Rumbo 11:", exc)
                print("Ejecute primero INSTALAR_RUMBO11.bat.")
                return 1

            try:
                call_command("check", verbosity=1)
            except Exception as exc:
                print("[ERROR] Las comprobaciones de Django fallaron:", exc)
                return 1

            host = os.getenv("RUMBO11_HOST", "127.0.0.1").strip() or "127.0.0.1"
            try:
                preferred = int(os.getenv("RUMBO11_PORT", "8000"))
            except ValueError:
                preferred = 8000
            port = choose_port(host, preferred)
            public_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
            url = f"http://{public_host}:{port}/"
            print("=" * 64)
            print("Rumbo 11 está disponible en:", url)
            print("Presione Ctrl+C para detenerlo de forma segura.")
            print("=" * 64)
            threading.Thread(target=open_browser, args=(url,), daemon=True).start()
            try:
                serve(application, host=host, port=port, threads=6, channel_timeout=120)
            except KeyboardInterrupt:
                print("\nRumbo 11 detenido correctamente.")
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
    ''')

    write(root / "scripts" / "migrate_safe.py", r'''
        from __future__ import annotations

        import os
        import subprocess
        import sys
        from pathlib import Path

        ROOT = Path(__file__).resolve().parents[1]
        PYTHON = Path(sys.executable)

        def run(*args: str) -> int:
            command = [str(PYTHON), str(ROOT / "manage.py"), *args]
            return subprocess.call(command, cwd=ROOT, env=os.environ.copy())

        def main() -> int:
            plan = subprocess.run(
                [str(PYTHON), str(ROOT / "manage.py"), "showmigrations", "--plan"],
                cwd=ROOT, capture_output=True, text=True
            )
            if plan.returncode != 0:
                print(plan.stdout)
                print(plan.stderr, file=sys.stderr)
                return plan.returncode
            pending = [line for line in plan.stdout.splitlines() if "[ ]" in line]
            if not pending:
                print("[OK] No hay migraciones pendientes.")
                return 0
            print("Migraciones pendientes detectadas:")
            for line in pending:
                print(" ", line)
            if run("create_backup", "--reason", "Respaldo automático previo a migraciones") != 0:
                print("[ERROR] No se pudo crear el respaldo previo.")
                return 1
            return run("migrate", "--noinput")

        if __name__ == "__main__":
            raise SystemExit(main())
    ''')


def create_bat_files(root: Path) -> None:
    write(root / "INSTALAR_RUMBO11.bat", r'''
        @echo off
        setlocal EnableExtensions EnableDelayedExpansion
        chcp 65001 >nul
        cd /d "%~dp0"
        title Instalación de Rumbo 11
        echo ================================================================
        echo                 INSTALADOR DE RUMBO 11
        echo ================================================================

        where py >nul 2>nul
        if not errorlevel 1 (
          set "PY_CMD=py -3.13"
        ) else (
          where python >nul 2>nul || goto :NO_PYTHON
          set "PY_CMD=python"
        )

        %PY_CMD% -c "import sys; assert sys.version_info >= (3, 10), sys.version" || goto :BAD_PYTHON
        if not exist ".venv\Scripts\python.exe" (
          echo [1/12] Creando entorno virtual...
          %PY_CMD% -m venv .venv || goto :FAIL
        ) else (
          echo [1/12] Se conservará el entorno virtual existente.
        )
        set "VPY=%CD%\.venv\Scripts\python.exe"

        echo [2/12] Actualizando herramientas de instalación...
        "%VPY%" -m pip install --upgrade pip setuptools wheel || goto :FAIL
        echo [3/12] Instalando dependencias controladas...
        if exist requirements.lock (
          "%VPY%" -m pip install -r requirements.lock || goto :FAIL
        ) else (
          "%VPY%" -m pip install -r requirements.txt || goto :FAIL
        )

        if not exist .env (
          echo [4/12] Creando configuración privada .env...
          copy /y .env.example .env >nul || goto :FAIL
          "%VPY%" -c "from pathlib import Path; import secrets; p=Path('.env'); s=p.read_text(encoding='utf-8'); s=s.replace('change-me-in-local-env', secrets.token_urlsafe(64)).replace('django-insecure-change-me', secrets.token_urlsafe(64)); p.write_text(s, encoding='utf-8')" || goto :FAIL
        ) else (
          echo [4/12] Se conservará el archivo .env existente.
        )

        echo [5/12] Creando carpetas locales...
        for %%D in (data data\backups data\exports data\tmp logs media staticfiles) do if not exist "%%D" mkdir "%%D"
        echo [6/12] Comprobando configuración...
        "%VPY%" manage.py check || goto :FAIL
        echo [7/12] Aplicando migraciones...
        "%VPY%" manage.py migrate --noinput || goto :FAIL
        echo [8/12] Sincronizando roles...
        "%VPY%" manage.py sync_roles || goto :FAIL
        echo [9/12] Recopilando archivos estáticos...
        "%VPY%" manage.py collectstatic --noinput || goto :FAIL
        echo [10/12] Creando administrador inicial...
        "%VPY%" manage.py create_initial_admin
        echo [11/12] Datos demostrativos opcionales.
        set /p DEMO="¿Crear datos demostrativos? [s/N]: "
        if /I "!DEMO!"=="s" "%VPY%" manage.py seed_demo
        echo [12/12] Ejecutando pruebas críticas...
        "%VPY%" manage.py test apps.core apps.accounts apps.backups --failfast || goto :FAIL
        echo.
        echo ================================================================
        echo Instalación finalizada correctamente.
        echo Use INICIAR_RUMBO11.bat para abrir la aplicación.
        echo ================================================================
        pause
        exit /b 0

        :NO_PYTHON
        echo [ERROR] Python no fue encontrado. Instale Python 3.13 de 64 bits.
        pause
        exit /b 1
        :BAD_PYTHON
        echo [ERROR] Se requiere Python 3.10 o superior; se recomienda 3.13.
        pause
        exit /b 1
        :FAIL
        echo.
        echo [ERROR] La instalación se detuvo para proteger sus datos.
        echo Revise el mensaje anterior y docs\TROUBLESHOOTING.md.
        pause
        exit /b 1
    ''')

    write(root / "INICIAR_RUMBO11.bat", r'''
        @echo off
        setlocal EnableExtensions
        chcp 65001 >nul
        cd /d "%~dp0"
        title Rumbo 11
        if not exist ".venv\Scripts\python.exe" (
          echo [ERROR] Rumbo 11 no está instalado.
          echo Ejecute primero INSTALAR_RUMBO11.bat.
          pause
          exit /b 1
        )
        set "VPY=%CD%\.venv\Scripts\python.exe"
        "%VPY%" manage.py check || goto :FAIL
        "%VPY%" scripts\migrate_safe.py || goto :FAIL
        "%VPY%" run_local.py
        exit /b %errorlevel%
        :FAIL
        echo [ERROR] El inicio fue detenido para proteger la información.
        pause
        exit /b 1
    ''')

    write(root / "ACTUALIZAR_RUMBO11.bat", r'''
        @echo off
        setlocal EnableExtensions
        chcp 65001 >nul
        cd /d "%~dp0"
        title Actualización de Rumbo 11
        if not exist ".venv\Scripts\python.exe" (
          echo [ERROR] Ejecute primero INSTALAR_RUMBO11.bat.
          pause
          exit /b 1
        )
        set "VPY=%CD%\.venv\Scripts\python.exe"
        echo [1/8] Creando respaldo obligatorio...
        "%VPY%" manage.py create_backup --reason "Respaldo previo a actualización" || goto :FAIL
        echo [2/8] Actualizando dependencias bloqueadas...
        "%VPY%" -m pip install -r requirements.lock || goto :FAIL
        echo [3/8] Comprobando cambios de modelos...
        "%VPY%" manage.py makemigrations --check --dry-run || goto :FAIL
        echo [4/8] Aplicando migraciones...
        "%VPY%" manage.py migrate --noinput || goto :FAIL
        echo [5/8] Sincronizando roles...
        "%VPY%" manage.py sync_roles || goto :FAIL
        echo [6/8] Actualizando archivos estáticos...
        "%VPY%" manage.py collectstatic --noinput || goto :FAIL
        echo [7/8] Ejecutando comprobaciones de seguridad...
        "%VPY%" manage.py check --deploy || goto :FAIL
        echo [8/8] Ejecutando pruebas críticas...
        "%VPY%" manage.py test apps.core apps.accounts apps.backups --failfast || goto :FAIL
        "%VPY%" manage.py system_report --output "data\exports\update_report.txt"
        echo Actualización finalizada sin eliminar la base de datos ni multimedia.
        pause
        exit /b 0
        :FAIL
        echo [ERROR] La actualización se detuvo. El respaldo previo se conserva.
        pause
        exit /b 1
    ''')

    write(root / "VERIFICAR_RUMBO11.bat", r'''
        @echo off
        setlocal
        chcp 65001 >nul
        cd /d "%~dp0"
        if not exist ".venv\Scripts\python.exe" (
          echo [ERROR] No existe el entorno virtual.
          pause
          exit /b 1
        )
        set "VPY=%CD%\.venv\Scripts\python.exe"
        "%VPY%" manage.py check
        "%VPY%" manage.py makemigrations --check --dry-run
        "%VPY%" manage.py migrate --plan
        "%VPY%" manage.py check_database
        "%VPY%" manage.py verify_media
        "%VPY%" -m coverage erase
        "%VPY%" -m coverage run manage.py test
        "%VPY%" -m coverage report -m
        "%VPY%" -m coverage html -d data\coverage_html
        pause
    ''')


def create_commands(root: Path) -> None:
    command_dir = root / "apps" / "core" / "management" / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)
    write(command_dir / "__init__.py", "")

    if not (command_dir / "create_initial_admin.py").exists():
        write(command_dir / "create_initial_admin.py", r'''
            from django.contrib.auth import get_user_model
            from django.core.management.base import BaseCommand, CommandError
            from django.db import transaction
            from getpass import getpass

            class Command(BaseCommand):
                help = "Crea el primer administrador sin sobrescribir usuarios existentes."

                def add_arguments(self, parser):
                    parser.add_argument("--username")
                    parser.add_argument("--email", default="")
                    parser.add_argument("--password")
                    parser.add_argument("--non-interactive", action="store_true")

                @transaction.atomic
                def handle(self, *args, **options):
                    User = get_user_model()
                    if User.objects.filter(is_superuser=True, is_active=True).exists():
                        self.stdout.write(self.style.SUCCESS("Ya existe un administrador activo."))
                        return
                    username = options.get("username")
                    password = options.get("password")
                    if not username and not options["non_interactive"]:
                        username = input("Usuario administrador: ").strip()
                    if not password and not options["non_interactive"]:
                        password = getpass("Contraseña temporal: ")
                    if not username or not password:
                        raise CommandError("Indique usuario y contraseña.")
                    extra = {"email": options.get("email", ""), "is_staff": True, "is_superuser": True}
                    field_names = {f.name for f in User._meta.fields}
                    if "role" in field_names:
                        extra["role"] = "administrator"
                    if "must_change_password" in field_names:
                        extra["must_change_password"] = True
                    user = User.objects.create_user(username=username, password=password, **extra)
                    self.stdout.write(self.style.SUCCESS(f"Administrador creado: {user.get_username()}"))
        ''')

    write(command_dir / "check_database.py", r'''
        from django.core.management import call_command
        from django.core.management.base import BaseCommand, CommandError
        from django.db import connection

        class Command(BaseCommand):
            help = "Comprueba integridad de SQLite y coherencia básica de Django."
            def handle(self, *args, **options):
                call_command("check")
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA integrity_check")
                    rows = [row[0] for row in cursor.fetchall()]
                    cursor.execute("PRAGMA foreign_key_check")
                    fk_rows = cursor.fetchall()
                if rows != ["ok"] or fk_rows:
                    raise CommandError(f"Integridad inválida: {rows}; FK: {fk_rows[:10]}")
                self.stdout.write(self.style.SUCCESS("Base de datos íntegra."))
    ''')

    write(command_dir / "create_backup.py", r'''
        from django.core.management import call_command
        from django.core.management.base import BaseCommand

        class Command(BaseCommand):
            help = "Alias estable para crear un respaldo local."
            def add_arguments(self, parser):
                parser.add_argument("--reason", default="Respaldo manual")
                parser.add_argument("--observations", default="")
            def handle(self, *args, **options):
                try:
                    call_command("create_local_backup", observations=options["observations"] or options["reason"])
                except TypeError:
                    call_command("create_local_backup")
    ''')

    write(command_dir / "restore_backup.py", r'''
        from django.core.management import call_command
        from django.core.management.base import BaseCommand, CommandError

        class Command(BaseCommand):
            help = "Alias seguro para restaurar un respaldo."
            def add_arguments(self, parser):
                parser.add_argument("backup")
                parser.add_argument("--confirm", required=True)
            def handle(self, *args, **options):
                if options["confirm"] != "RESTAURAR":
                    raise CommandError("Use --confirm RESTAURAR para autorizar la operación.")
                call_command("restore_local_backup", options["backup"], confirm="RESTAURAR")
    ''')

    write(command_dir / "cleanup_temp_files.py", r'''
        from django.core.management import call_command
        from django.core.management.base import BaseCommand

        class Command(BaseCommand):
            help = "Alias estable para limpiar archivos temporales."
            def add_arguments(self, parser):
                parser.add_argument("--days", type=int, default=7)
            def handle(self, *args, **options):
                try:
                    call_command("cleanup_temporary_files", days=options["days"])
                except TypeError:
                    call_command("cleanup_temporary_files")
    ''')

    write(command_dir / "verify_media.py", r'''
        from pathlib import Path
        from django.apps import apps
        from django.conf import settings
        from django.core.management.base import BaseCommand, CommandError
        from django.db.models import FileField

        class Command(BaseCommand):
            help = "Verifica archivos referenciados por campos FileField/ImageField."
            def add_arguments(self, parser):
                parser.add_argument("--strict", action="store_true")
            def handle(self, *args, **options):
                missing = []
                checked = 0
                for model in apps.get_models():
                    file_fields = [f for f in model._meta.fields if isinstance(f, FileField)]
                    if not file_fields:
                        continue
                    for obj in model._default_manager.all().iterator(chunk_size=200):
                        for field in file_fields:
                            value = getattr(obj, field.name, None)
                            if value and getattr(value, "name", ""):
                                checked += 1
                                try:
                                    exists = value.storage.exists(value.name)
                                except Exception:
                                    exists = False
                                if not exists:
                                    missing.append(f"{model._meta.label}:{obj.pk}:{field.name}:{value.name}")
                for item in missing[:50]:
                    self.stdout.write(self.style.WARNING(item))
                self.stdout.write(f"Archivos verificados: {checked}; faltantes: {len(missing)}")
                if missing and options["strict"]:
                    raise CommandError("Existen archivos multimedia faltantes.")
    ''')

    write(command_dir / "system_report.py", r'''
        import json
        import platform
        import sys
        from pathlib import Path
        from django.apps import apps
        from django.conf import settings
        from django.core.management import call_command
        from django.core.management.base import BaseCommand
        from django.db import connection

        class Command(BaseCommand):
            help = "Genera un informe técnico sin secretos."
            def add_arguments(self, parser):
                parser.add_argument("--output")
            def handle(self, *args, **options):
                report = {
                    "application": "Rumbo 11",
                    "version": (Path(settings.BASE_DIR) / "VERSION").read_text(encoding="utf-8").strip(),
                    "python": sys.version.split()[0],
                    "platform": platform.platform(),
                    "debug": bool(settings.DEBUG),
                    "database_engine": connection.vendor,
                    "installed_apps": len(settings.INSTALLED_APPS),
                    "models": len(list(apps.get_models())),
                }
                text = json.dumps(report, ensure_ascii=False, indent=2)
                if options.get("output"):
                    path = Path(options["output"])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text + "\n", encoding="utf-8")
                    self.stdout.write(self.style.SUCCESS(f"Informe creado: {path}"))
                else:
                    self.stdout.write(text)
    ''')

    write(command_dir / "export_results.py", r'''
        import csv
        from pathlib import Path
        from django.apps import apps
        from django.core.management.base import BaseCommand, CommandError

        class Command(BaseCommand):
            help = "Exporta resultados académicos mínimos a CSV."
            def add_arguments(self, parser):
                parser.add_argument("--output", required=True)
            def handle(self, *args, **options):
                candidates = [
                    ("simulations", "SimulationAttempt"),
                    ("practice", "PracticeAttempt"),
                    ("practice", "DiagnosticAttempt"),
                ]
                path = Path(options["output"])
                path.parent.mkdir(parents=True, exist_ok=True)
                rows = []
                for app_label, model_name in candidates:
                    try:
                        Model = apps.get_model(app_label, model_name)
                    except LookupError:
                        continue
                    field_names = {f.name for f in Model._meta.fields}
                    for obj in Model.objects.all().iterator(chunk_size=200):
                        rows.append({
                            "tipo": model_name,
                            "id": str(obj.pk),
                            "estudiante_id": str(getattr(obj, "student_id", "")),
                            "estado": str(getattr(obj, "status", "")),
                            "aciertos": getattr(obj, "correct_answers", ""),
                            "porcentaje": getattr(obj, "percentage", getattr(obj, "score_percentage", "")),
                            "fecha": str(getattr(obj, "finished_at", getattr(obj, "created_at", ""))),
                        })
                with path.open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["tipo", "id", "estudiante_id", "estado", "aciertos", "porcentaje", "fecha"])
                    writer.writeheader()
                    writer.writerows(rows)
                self.stdout.write(self.style.SUCCESS(f"Exportados {len(rows)} registros a {path}"))
    ''')

    write(command_dir / "seed_demo.py", r'''
        from __future__ import annotations

        from datetime import date, timedelta
        from django.apps import apps
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        from django.core.management.base import BaseCommand
        from django.db import models, transaction
        from django.utils import timezone

        DEMO_PASSWORD = "Rumbo11-Demo-2026!"

        def fields(model):
            return {f.name: f for f in model._meta.fields}

        def filtered(model, values):
            names = fields(model)
            return {k: v for k, v in values.items() if k in names and v is not None}

        def choice_value(field, preferred):
            values = [str(value) for value, _ in (field.choices or [])]
            for item in preferred:
                if item in values:
                    return item
            return values[0] if values else None

        def required_defaults(model, label="Demostración"):
            result = {}
            for field in model._meta.fields:
                if field.primary_key or field.auto_created or field.has_default() or field.null or field.blank:
                    continue
                if field.is_relation:
                    related = field.remote_field.model.objects.first()
                    if related is not None:
                        result[field.name] = related
                    continue
                if field.choices:
                    result[field.name] = field.choices[0][0]
                elif isinstance(field, (models.CharField, models.TextField)):
                    result[field.name] = label[: getattr(field, "max_length", None) or 200]
                elif isinstance(field, models.BooleanField):
                    result[field.name] = True
                elif isinstance(field, (models.IntegerField, models.PositiveIntegerField)):
                    result[field.name] = 1
                elif isinstance(field, (models.FloatField, models.DecimalField)):
                    result[field.name] = 0
                elif isinstance(field, models.DateTimeField):
                    result[field.name] = timezone.now()
                elif isinstance(field, models.DateField):
                    result[field.name] = date.today()
                elif isinstance(field, models.JSONField):
                    result[field.name] = {}
            return result

        def safe_update_or_create(model, lookup, values):
            payload = required_defaults(model)
            payload.update(filtered(model, values))
            return model.objects.update_or_create(defaults=payload, **filtered(model, lookup))[0]

        class Command(BaseCommand):
            help = "Crea datos demostrativos idempotentes sin usar información real."

            def add_arguments(self, parser):
                parser.add_argument("--show-credentials", action="store_true")

            @transaction.atomic
            def handle(self, *args, **options):
                try:
                    call_command("seed_academic_2026")
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f"La estructura académica existente se conservará: {exc}"))

                User = get_user_model()
                user_fields = fields(User)
                def user(username, role, first, last):
                    defaults = filtered(User, {
                        "first_name": first, "last_name": last, "email": "",
                        "role": role, "is_active": True,
                        "is_staff": role == "administrator", "is_superuser": role == "administrator",
                        "must_change_password": True,
                    })
                    obj, created = User.objects.update_or_create(username=username, defaults=defaults)
                    if created or not obj.has_usable_password():
                        obj.set_password(DEMO_PASSWORD)
                        obj.save(update_fields=["password"])
                    return obj

                admin = user("demo_admin", "administrator", "Administrador", "Demostración")
                teacher = user("demo_profesor", "teacher", "Docente", "Demostración")
                students = [
                    user("demo_estudiante1", "student", "Estudiante", "Uno"),
                    user("demo_estudiante2", "student", "Estudiante", "Dos"),
                ]

                institution = group = None
                try:
                    Institution = apps.get_model("institutions", "Institution")
                    institution = safe_update_or_create(Institution, {"code": "DEMO"}, {
                        "name": "Institución Demostrativa Rumbo 11", "active": True, "is_active": True,
                    })
                    Campus = apps.get_model("institutions", "Campus")
                    campus = safe_update_or_create(Campus, {"institution": institution, "code": "PRINCIPAL"}, {
                        "name": "Sede principal", "active": True, "is_active": True,
                    })
                    AcademicYear = apps.get_model("institutions", "AcademicYear")
                    year = safe_update_or_create(AcademicYear, {"year": date.today().year}, {
                        "institution": institution, "name": str(date.today().year),
                        "start_date": date(date.today().year, 1, 15), "end_date": date(date.today().year, 12, 15),
                        "active": True, "is_active": True,
                    })
                    Grade = apps.get_model("institutions", "Grade")
                    grade = safe_update_or_create(Grade, {"code": "11"}, {"name": "Grado 11", "order": 11, "active": True, "is_active": True})
                    Group = apps.get_model("institutions", "AcademicGroup")
                    group = safe_update_or_create(Group, {"name": "11° Demo", "teacher": teacher}, {
                        "institution": institution, "campus": campus, "academic_year": year, "grade": grade,
                        "active": True, "is_active": True,
                    })
                    Enrollment = apps.get_model("institutions", "Enrollment")
                    for student in students:
                        safe_update_or_create(Enrollment, {"group": group, "student": student}, {"status": "active", "active": True, "is_active": True})
                except LookupError as exc:
                    self.stdout.write(self.style.WARNING(f"Modelos institucionales no disponibles: {exc}"))

                # Marca o crea contenido demostrativo básico mediante introspección.
                created_summary = []
                for app_label, model_name, count in [
                    ("lessons", "Lesson", 5),
                    ("question_bank", "Question", 20),
                    ("practice", "Practice", 1),
                    ("simulations", "Simulation", 1),
                    ("study_plans", "StudyPlan", 1),
                ]:
                    try:
                        Model = apps.get_model(app_label, model_name)
                    except LookupError:
                        continue
                    existing = Model.objects.filter(**filtered(Model, {"is_demo": True})).count() if "is_demo" in fields(Model) else 0
                    needed = max(0, count - existing)
                    for index in range(needed):
                        values = {
                            "name": f"{model_name} demostrativo {index + 1}",
                            "title": f"{model_name} demostrativo {index + 1}",
                            "code": f"DEMO-{model_name[:4].upper()}-{index + 1:03d}",
                            "description": "Contenido demostrativo pendiente de validación académica.",
                            "statement": "Contenido demostrativo pendiente de validación académica.",
                            "general_explanation": "Ejemplo creado únicamente para comprobar el funcionamiento local.",
                            "source": "Contenido original de demostración de Rumbo 11",
                            "license": "Uso educativo interno",
                            "author": teacher,
                            "student": students[index % len(students)],
                            "created_by": teacher,
                            "is_demo": True,
                            "demo_disclaimer": "Contenido demostrativo pendiente de validación académica.",
                            "active": True, "is_active": True,
                        }
                        status_field = fields(Model).get("status")
                        if status_field:
                            values["status"] = choice_value(status_field, ["published", "active", "draft"])
                        try:
                            payload = required_defaults(Model, values["description"])
                            payload.update(filtered(Model, values))
                            obj = Model.objects.create(**payload)
                            created_summary.append(f"{Model._meta.label}:{obj.pk}")
                        except Exception as exc:
                            self.stdout.write(self.style.WARNING(f"No se creó {Model._meta.label}: {exc}"))
                            break

                self.stdout.write(self.style.SUCCESS("Datos demostrativos preparados de forma idempotente."))
                if options["show_credentials"]:
                    self.stdout.write("Credenciales temporales SOLO PARA DESARROLLO:")
                    self.stdout.write("  demo_admin / " + DEMO_PASSWORD)
                    self.stdout.write("  demo_profesor / " + DEMO_PASSWORD)
                    self.stdout.write("  demo_estudiante1 / " + DEMO_PASSWORD)
                    self.stdout.write("  demo_estudiante2 / " + DEMO_PASSWORD)
                else:
                    self.stdout.write("Use --show-credentials únicamente en desarrollo para mostrar las credenciales.")
    ''')


def create_docs(root: Path) -> None:
    write(root / ".coveragerc", '''
        [run]
        branch = True
        source = apps,config
        omit =
            */migrations/*
            */tests/*
            manage.py

        [report]
        show_missing = True
        skip_covered = False
        precision = 2
        exclude_lines =
            pragma: no cover
            if __name__ == .__main__.:
    ''')

    write(root / "docs" / "ADMIN_MANUAL.md", '''
        # Manual del administrador

        ## Instalación y acceso
        Ejecute `INSTALAR_RUMBO11.bat`, cree el administrador inicial y luego abra
        `INICIAR_RUMBO11.bat`. La contraseña inicial debe cambiarse en el primer acceso.

        ## Operación cotidiana
        1. Cree instituciones, sedes, años, grados y grupos.
        2. Cree usuarios con el rol mínimo necesario.
        3. Mantenga versionada la estructura académica.
        4. Cree, revise y publique preguntas; nunca modifique silenciosamente una publicada.
        5. Importe preguntas únicamente después de revisar la vista previa.
        6. Publique lecciones y simulacros después de validarlos.
        7. Consulte reportes y auditoría sin exportar datos personales innecesarios.

        ## Respaldo y restauración
        Cree un respaldo antes de actualizaciones y cambios masivos. Para restaurar, use el
        panel de respaldos o `python manage.py restore_backup ARCHIVO --confirm RESTAURAR`.
        La restauración genera un respaldo preventivo y nunca debe interrumpirse.

        ## Mantenimiento
        Ejecute periódicamente `check_database`, `verify_media`, `cleanup_temp_files` y
        `system_report`. Conserve varias copias en un medio externo protegido.
    ''')

    write(root / "docs" / "TEACHER_MANUAL.md", '''
        # Manual del profesor

        1. Ingrese con su cuenta docente.
        2. Cree un grupo o abra uno asignado.
        3. Vincule estudiantes mediante matrícula o código temporal.
        4. Cree actividades con fechas claras y recursos publicados.
        5. Configure prácticas y programe simulacros.
        6. Consulte resultados individuales y grupales.
        7. Revise competencias débiles, errores frecuentes e inactividad.
        8. Registre observaciones académicas respetuosas y necesarias.
        9. Exporte solamente los datos requeridos para la labor pedagógica.

        Los puntajes de Rumbo 11 son estimaciones educativas; no son resultados oficiales
        del ICFES ni reproducen su modelo psicométrico.
    ''')

    write(root / "docs" / "STUDENT_MANUAL.md", '''
        # Manual del estudiante

        1. Inicie sesión y cambie la contraseña temporal.
        2. Ajuste contraste, tamaño de texto o modo oscuro desde Accesibilidad.
        3. Realice el diagnóstico inicial sin buscar respuestas externas.
        4. Siga el plan de estudio y consulte las lecciones recomendadas.
        5. Practique; las respuestas se guardan automáticamente.
        6. Presente simulacros dentro de las fechas indicadas.
        7. Revise explicaciones, preguntas marcadas y cuaderno de errores.
        8. Complete los repasos programados.

        Ante un cierre accidental, vuelva a ingresar para recuperar el intento. No comparta
        su contraseña y cierre sesión en computadores de uso común.
    ''')

    write(root / "docs" / "TROUBLESHOOTING.md", '''
        # Solución de problemas

        ## Python no encontrado
        Instale Python 3.13 de 64 bits y habilite el lanzador `py`. Reinicie Windows y
        vuelva a ejecutar el instalador.

        ## Puerto ocupado
        Rumbo 11 busca automáticamente otro puerto entre el configurado y los 19 siguientes.
        También puede cambiar `RUMBO11_PORT` en `.env`.

        ## Entorno virtual dañado
        Cierre Rumbo 11, cambie el nombre de `.venv` a `.venv_anterior` y ejecute nuevamente
        `INSTALAR_RUMBO11.bat`. No elimine `data/` ni `media/`.

        ## Migración pendiente
        Ejecute `INICIAR_RUMBO11.bat`; el iniciador crea respaldo y aplica migraciones.

        ## Base de datos bloqueada
        Cierre todas las consolas de Rumbo 11, espere unos segundos y ejecute
        `python manage.py check_database` desde el entorno virtual.

        ## Archivos estáticos faltantes
        Ejecute `.venv\\Scripts\\python manage.py collectstatic --noinput`.

        ## Error de permisos
        Confirme el rol, el grupo propietario y el estado activo del usuario. No otorgue
        permisos globales para resolver un problema de propiedad.

        ## El navegador no abre
        Copie la URL mostrada en la consola, normalmente `http://127.0.0.1:8000/`.

        ## Acceso desde red local
        Configure `RUMBO11_HOST=0.0.0.0`, agregue de forma restrictiva el host permitido y
        autorice el puerto en Firewall de Windows. No exponga el sistema a internet.

        ## Restauración
        Valide primero el ZIP. Mantenga el equipo encendido durante toda la restauración.
        Ante un fallo, conserve tanto el respaldo elegido como el preventivo.
    ''')

    write(root / "docs" / "INSTALLATION.md", '''
        # Instalación final en Windows

        Requisitos: Windows 10/11 de 64 bits, Python 3.13, 4 GB de RAM como mínimo y espacio
        libre para la base de datos, multimedia y respaldos.

        1. Extraiga el ZIP completo en una carpeta con permisos de escritura.
        2. Ejecute `INSTALAR_RUMBO11.bat`.
        3. Revise cada paso; el instalador se detiene ante errores críticos.
        4. Cree el administrador inicial.
        5. Los datos demostrativos son opcionales.
        6. Use `INICIAR_RUMBO11.bat` para el uso cotidiano.

        La aplicación funciona localmente y no utiliza CDN. Se requiere conexión únicamente
        durante la primera instalación de las dependencias, salvo que disponga de paquetes
        Python descargados previamente.
    ''')

    append_once(root / "README.md", "## Entrega final 1.0.0", '''
        ## Entrega final 1.0.0

        Rumbo 11 es una aplicación local en Django para preparar Saber 11 mediante lecciones,
        diagnóstico, prácticas, simulacros, seguimiento docente, reportes y respaldos.

        ### Requisitos
        - Windows 10 u 11 de 64 bits.
        - Python 3.13 recomendado; mínimo compatible: 3.10.
        - Navegador moderno.

        ### Instalación e inicio
        1. Ejecute `INSTALAR_RUMBO11.bat` una sola vez.
        2. Use `INICIAR_RUMBO11.bat` para abrir la aplicación.
        3. Use `ACTUALIZAR_RUMBO11.bat` para actualizaciones controladas.
        4. Use `VERIFICAR_RUMBO11.bat` para pruebas y cobertura.

        ### Documentación
        Consulte `docs/INSTALLATION.md`, `docs/ADMIN_MANUAL.md`,
        `docs/TEACHER_MANUAL.md`, `docs/STUDENT_MANUAL.md` y
        `docs/TROUBLESHOOTING.md`.

        ### Credenciales demostrativas
        Solo se muestran al ejecutar `python manage.py seed_demo --show-credentials`.
        Todas las cuentas demostrativas deben cambiar la contraseña en un uso real.

        ### Advertencia
        Rumbo 11 no es una herramienta oficial del ICFES. Sus puntajes son estimaciones
        educativas y no reproducen el modelo psicométrico oficial.
    ''')

    append_once(root / "CHANGELOG.md", "## [1.0.0]", '''
        ## [1.0.0] - Entrega final
        - Instalador, iniciador y actualizador definitivos para Windows.
        - Servidor local Waitress sin dependencia de `runserver`.
        - Dependencias bloqueadas y actualización conservadora.
        - Comando `seed_demo` y comandos operativos estables.
        - Manuales completos de administración, docencia, estudiantes e instalación.
        - Verificación de entrega, pruebas críticas y cobertura reproducible.
        - Manifiesto final y protección de base de datos y multimedia durante actualizaciones.
    ''')

    write(root / "FINAL_DELIVERY_REPORT.md", '''
        # Informe final de entrega — Rumbo 11 v1.0.0

        La versión final reúne las fases 0 a 10. El sistema utiliza Django, SQLite y Waitress,
        funciona localmente, no usa CDN, protege datos existentes durante actualizaciones y
        mantiene separados los dominios de usuarios, estructura académica, preguntas,
        lecciones, prácticas, simulacros, analítica, reportes, privacidad y respaldos.

        ## Verificación en el equipo de destino
        Ejecute `VERIFICAR_RUMBO11.bat`. Este comando realiza comprobaciones de Django,
        coherencia de migraciones, plan de migración, integridad de SQLite, multimedia,
        pruebas automatizadas e informe HTML de cobertura.

        La distribución no incluye `.env`, base de datos, multimedia privada, registros,
        entornos virtuales ni respaldos del usuario.
    ''')


def create_verifier(root: Path) -> None:
    write(root / "verify_release.py", r'''
        from __future__ import annotations
        import ast
        import json
        import re
        import sys
        from pathlib import Path

        ROOT = Path(__file__).resolve().parent
        REQUIRED = [
            "manage.py", "VERSION", "requirements.txt", "requirements.lock",
            "INSTALAR_RUMBO11.bat", "INICIAR_RUMBO11.bat", "ACTUALIZAR_RUMBO11.bat",
            "VERIFICAR_RUMBO11.bat", "run_local.py", ".env.example",
            "docs/INSTALLATION.md", "docs/ADMIN_MANUAL.md", "docs/TEACHER_MANUAL.md",
            "docs/STUDENT_MANUAL.md", "docs/TROUBLESHOOTING.md",
        ]
        errors = []
        for item in REQUIRED:
            if not (ROOT / item).exists():
                errors.append("Falta " + item)
        py_count = test_count = 0
        for path in ROOT.rglob("*.py"):
            if any(part in {".venv", "venv", "__pycache__"} for part in path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                py_count += 1
                test_count += sum(1 for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"))
            except Exception as exc:
                errors.append(f"Python inválido {path.relative_to(ROOT)}: {exc}")
        forbidden = ["cdn.jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com"]
        for path in list(ROOT.rglob("*.html")) + list(ROOT.rglob("*.js")) + list(ROOT.rglob("*.css")):
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for token in forbidden:
                if token in text:
                    errors.append(f"CDN detectado en {path.relative_to(ROOT)}: {token}")
        for secret in [ROOT / ".env", ROOT / "data" / "db.sqlite3"]:
            if secret.exists():
                errors.append(f"Archivo privado presente: {secret.relative_to(ROOT)}")
        print(f"Archivos Python válidos: {py_count}")
        print(f"Pruebas detectadas: {test_count}")
        if errors:
            for error in errors:
                print("[ERROR]", error)
            raise SystemExit(1)
        print("[OK] Verificación estática de la entrega final superada.")
    ''')


def package(root: Path, output_dir: Path) -> tuple[Path, Path, dict]:
    excluded_parts = {".venv", "venv", "__pycache__", ".git", "logs", "backups", "coverage_html"}
    excluded_names = {".env", "db.sqlite3", ".coverage"}
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in excluded_parts for part in rel.parts) or path.name in excluded_names:
            continue
        if path.suffix in {".pyc", ".pyo", ".log"}:
            continue
        files.append((path, rel))
    files.sort(key=lambda pair: pair[1].as_posix())
    manifest = {
        "product": PRODUCT,
        "version": VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "files": [],
    }
    for path, rel in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["files"].append({"path": rel.as_posix(), "size": path.stat().st_size, "sha256": digest})
    write(root / "RELEASE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    # Include the newly created manifest itself.
    files.append((root / "RELEASE_MANIFEST.json", Path("RELEASE_MANIFEST.json")))
    target = output_dir / FINAL_ZIP
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path, rel in files:
            zf.write(path, Path("rumbo11") / rel)
    with zipfile.ZipFile(target) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError("Archivo ZIP dañado: " + bad)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    sha_path = output_dir / (target.name + ".sha256")
    sha_path.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return target, sha_path, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase9_zip", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    parser.add_argument("--keep-workdir", action="store_true")
    args = parser.parse_args()
    source = args.phase9_zip.resolve()
    if not source.is_file() or not zipfile.is_zipfile(source):
        parser.error("Indique un ZIP válido de Rumbo 11 Fase 9.")
    work = Path(tempfile.mkdtemp(prefix="rumbo11_phase10_"))
    try:
        with zipfile.ZipFile(source) as zf:
            for info in zf.infolist():
                candidate = (work / info.filename).resolve()
                if work.resolve() not in candidate.parents and candidate != work.resolve():
                    raise RuntimeError("El ZIP contiene una ruta insegura.")
            zf.extractall(work)
        root = find_root(work)
        create_runtime(root)
        create_bat_files(root)
        create_commands(root)
        create_docs(root)
        create_verifier(root)
        # Static syntax verification.
        py_count = 0
        for path in root.rglob("*.py"):
            if any(part in {".venv", "venv", "__pycache__"} for part in path.parts):
                continue
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            py_count += 1
        args.output_dir.mkdir(parents=True, exist_ok=True)
        target, sha_path, manifest = package(root, args.output_dir.resolve())
        print(f"[OK] {py_count} archivos Python analizados.")
        print(f"[OK] {manifest['file_count']} archivos incluidos.")
        print(f"[OK] Paquete: {target}")
        print(f"[OK] SHA-256: {sha_path}")
        if args.keep_workdir:
            print(f"Carpeta temporal conservada: {work}")
            return 0
        return 0
    finally:
        if work.exists() and not args.keep_workdir:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
