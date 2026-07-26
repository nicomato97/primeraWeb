# Kit reproducible de la Fase 10 — Rumbo 11

Este kit transforma el paquete oficial `Rumbo11_Fase_9_v0.9.0.zip` en la entrega final `Rumbo11_Final_v1.0.0.zip` sin modificar el archivo de entrada.

## Uso en Windows

1. Coloque en la misma carpeta:
   - `Rumbo11_Fase_9_v0.9.0.zip`
   - `finalize_phase10.py`
   - `CONSTRUIR_FASE10.bat`
2. Ejecute `CONSTRUIR_FASE10.bat`.
3. El proceso crea:
   - `Rumbo11_Final_v1.0.0.zip`
   - `Rumbo11_Final_v1.0.0.zip.sha256`

## Qué incorpora

- Versión 1.0.0.
- Instalador definitivo para Windows.
- Iniciador local mediante Waitress.
- Actualizador con respaldo previo.
- Dependencias bloqueadas.
- Comando `seed_demo`.
- Comandos de operación solicitados.
- Manuales para administrador, profesor y estudiante.
- Guía de instalación y solución de problemas.
- Verificador estático de la distribución.
- Ejecución reproducible de pruebas y cobertura.
- Manifiesto SHA-256 de archivos distribuidos.

## Seguridad

El paquete final excluye `.env`, bases de datos locales, multimedia privada, registros, respaldos, entornos virtuales y archivos temporales.

El constructor no afirma que las pruebas dinámicas de Django hayan pasado. Estas deben ejecutarse en el computador de destino mediante `VERIFICAR_RUMBO11.bat`, una vez instaladas las dependencias.
