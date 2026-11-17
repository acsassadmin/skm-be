import ssl
from django.core.mail.backends.smtp import EmailBackend as DjangoEmailBackend


class Python312EmailBackend(DjangoEmailBackend):
    def _build_ssl_context(self):
        context = ssl.create_default_context()
        if self.ssl_certfile or self.ssl_keyfile:
            context.load_cert_chain(
                certfile=self.ssl_certfile,
                keyfile=self.ssl_keyfile,
            )
        return context

    def open(self):
        if self.connection:
            return False

        connection_params = {}
        if self.timeout is not None:
            connection_params["timeout"] = self.timeout
        if self.use_ssl:
            connection_params["context"] = self._build_ssl_context()

        try:
            self.connection = self.connection_class(
                self.host, self.port, **connection_params
            )
            if not self.use_ssl and self.use_tls:
                self.connection.starttls(context=self._build_ssl_context())
            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except OSError:
            if not self.fail_silently:
                raise
