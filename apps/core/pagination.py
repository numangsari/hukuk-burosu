"""Liste başına kayıt sayısı seçimi."""

PAGE_SIZES = (10, 25, 50, 100)


def page_size(request, default=25):
    key = "page_size:" + request.path
    selected = request.GET.get("sayfa_boyutu", "")
    if selected in {str(size) for size in PAGE_SIZES}:
        value = int(selected)
        request.session[key] = value
        return value
    saved = request.session.get(key, default)
    return saved if saved in PAGE_SIZES else default
