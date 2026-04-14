def user_groups(request):
    """agrega la lista de grupos del usuario al contexto de todos los templates"""
    if request.user.is_authenticated:
        return {'user_groups': list(request.user.groups.values_list('name', flat=True))}
    return {'user_groups': []}
