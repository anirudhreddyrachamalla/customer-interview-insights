"""Storage backends for audio + transcript files.

The default backend is the local filesystem (handled directly by
:mod:`app.services.audio`). When ``settings.storage_backend == "azure_blob"``
the audio service dispatches into :mod:`app.storage.azure_blob`, which
wraps ``azure.storage.blob.aio`` with ``DefaultAzureCredential`` so
managed-identity authentication works automatically on Azure App Service
while ``az login`` works locally.
"""
