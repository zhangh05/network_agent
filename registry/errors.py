# registry/errors.py
"""Registry-specific error types."""


class RegistryError(Exception): pass
class ModuleNotFoundError(RegistryError): pass
class SkillNotFoundError(RegistryError): pass
class CapabilityNotFoundError(RegistryError): pass
class ValidationError(RegistryError): pass
class ContractViolationError(RegistryError): pass
class RegistryConflictError(RegistryError): pass
