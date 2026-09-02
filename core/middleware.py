from core.services.llm_identity import bind_request


class LlmIdentityMiddleware:
    """Запомнить IP до DRF, чтобы фоновые LLM-потоки знали, кого лимитировать."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        bind_request(request)
        return self.get_response(request)
