class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        self.code, self.message, self.status = code, message, status
        self.context = {}
        super().__init__(message)

    def payload(self):
        return {"erro": {"codigo": self.code, "mensagem": self.message, **self.context}}
