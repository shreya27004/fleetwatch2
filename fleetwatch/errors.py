"""Domain errors. The API layer maps each one to an HTTP status code."""


class FleetError(Exception):
    http_status = 500


class ValidationError(FleetError):
    http_status = 400


class DeviceNotFound(FleetError):
    http_status = 404


class DeviceAlreadyExists(FleetError):
    http_status = 409
