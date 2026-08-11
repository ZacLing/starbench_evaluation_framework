"""Errors shared by launch-request validation and run supervision."""


class LaunchError(ValueError):
    pass


__all__ = ["LaunchError"]
