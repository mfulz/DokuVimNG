class DokuVimNGError(Exception):
    def __init__(self, err, msg="DokuVimNG Error"):
        self._msg = msg
        self._err = err
        super().__init__(self._err)

    def __str__(self):
        return f"{self._msg}: {self._err}"


class DWInitError(DokuVimNGError):
    def __init__(self, msg="Unable to init"):
        self._msg = msg
        super().__init__(self._msg)


class DWConnectError(DokuVimNGError):
    def __init__(self, msg="Unable to connect"):
        self._msg = msg
        super().__init__(self._msg)
