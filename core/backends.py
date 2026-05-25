"""
Backend de autenticación dual para GPIV.

Permite que el usuario se identifique usando su nombre de usuario (username)
o su correo electrónico (email) de forma indistinta.

El manejo de errores es silencioso: no se revela si el email existe en la
base de datos cuando la contraseña es incorrecta.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Backend personalizado que extiende ModelBackend para soportar
    autenticación tanto por username como por email.

    Orden de búsqueda:
    1. Busca al usuario por username (exacto, comportamiento estándar).
    2. Si no lo encuentra, busca por email (insensible a mayúsculas).

    En caso de múltiples coincidencias por email (no debería ocurrir si el
    campo es unique), se ignoran todas y no se autentica a nadie.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()

        if username is None or password is None:
            return None

        # --- Intento 1: buscar por username exacto ---
        try:
            user = UserModel.objects.get(username=username)
        except UserModel.DoesNotExist:
            user = None

        # --- Intento 2: buscar por email (case-insensitive) ---
        if user is None:
            try:
                user = UserModel.objects.get(email__iexact=username)
            except UserModel.DoesNotExist:
                # Ejecutamos el hasher igualmente para mitigar timing attacks
                UserModel().set_password(password)
                return None
            except UserModel.MultipleObjectsReturned:
                # Emails duplicados: comportamiento seguro, no autenticar
                return None

        # Verificar contraseña y que el usuario pueda autenticarse
        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
