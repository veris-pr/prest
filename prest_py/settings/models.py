from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuthSettings(BaseModel):
    enabled: bool = False
    username: str = "username"
    password: str = "password"
    schema_: str = Field(default="public", alias="schema")
    table: str = "prest_users"
    encrypt: str = "bcrypt"
    type: str = "body"
    metadata: list[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class HTTPSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=3000, ge=1, le=65535)
    timeout: int = Field(default=60, ge=0)


class SSLSettings(BaseModel):
    mode: str = "disable"
    cert: str = ""
    key: str = ""
    rootcert: str = ""


class PGSettings(BaseModel):
    url: str = ""
    host: str = "127.0.0.1"
    port: int = Field(default=5432, ge=1, le=65535)
    user: str = "postgres"
    pass_: str = Field(default="postgres", alias="pass")
    database: str = "prest"
    ssl: SSLSettings = Field(default_factory=SSLSettings)
    maxidleconn: int = 0
    maxopenconn: int = 10
    conntimeout: int = 10
    single: bool = True
    cache: bool = True

    model_config = ConfigDict(populate_by_name=True)


class CacheEndpointSettings(BaseModel):
    enabled: bool = False
    endpoint: str = ""
    time: int = 0


class CacheSettings(BaseModel):
    enabled: bool = False
    time: int = 10
    storagepath: str = "./"
    sufixfile: str = ".cache.prestd.db"
    endpoints: list[CacheEndpointSettings] = Field(default_factory=list)


class AccessTableSettings(BaseModel):
    database: str = ""
    schema_: str = Field(default="", alias="schema")
    name: str = ""
    permissions: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class AccessUserSettings(BaseModel):
    name: str = ""
    tables: list[AccessTableSettings] = Field(default_factory=list)


class AccessSettings(BaseModel):
    restrict: bool = False
    ignore_table: list[str] = Field(default_factory=list)
    tables: list[AccessTableSettings] = Field(default_factory=list)
    users: list[AccessUserSettings] = Field(default_factory=list)


class ExposeSettings(BaseModel):
    enabled: bool = False
    tables: bool = True
    schemas: bool = True
    databases: bool = True


class DatabaseSettings(BaseModel):
    alias: str
    url: str = ""
    host: str = ""
    port: int = 0
    user: str = ""
    pass_: str = Field(default="", alias="pass")
    database: str = ""
    ssl: SSLSettings = Field(default_factory=SSLSettings)
    maxopenconn: int = 0
    maxidleconn: int = 0

    model_config = ConfigDict(populate_by_name=True)


class JWTSettings(BaseModel):
    default: bool = False
    key: str = ""
    algo: str = "HS256"
    wellknownurl: str = ""
    jwks: str = ""
    whitelist: list[str] = Field(default_factory=lambda: [r"^\/auth$"])


class QueriesSettings(BaseModel):
    location: str = ""


class PluginsSettings(BaseModel):
    entries: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    """Runtime settings for the Python rewrite.

    Phase 2 grows this toward pREST TOML/env compatibility. Loader behavior lives
    in `prest_py.settings.loader` so the model stays declarative and testable.
    """

    app_name: str = "pREST Python"
    config_path: str = "./prest.toml"
    debug: bool = False
    context: str = "/"
    auth: AuthSettings = Field(default_factory=AuthSettings)
    http: HTTPSettings = Field(default_factory=HTTPSettings)
    pg: PGSettings = Field(default_factory=PGSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    access: AccessSettings = Field(default_factory=AccessSettings)
    expose: ExposeSettings = Field(default_factory=ExposeSettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    queries: QueriesSettings = Field(default_factory=QueriesSettings)
    plugins: PluginsSettings = Field(default_factory=PluginsSettings)
    databases: list[DatabaseSettings] = Field(default_factory=list)

    json_agg_type: str = "jsonb_agg"

    @property
    def http_host(self) -> str:
        return self.http.host

    @property
    def http_port(self) -> int:
        return self.http.port

    @property
    def has_database_registry(self) -> bool:
        return bool(self.databases)

    def profile_by_alias(self, alias: str) -> DatabaseSettings | None:
        for database in self.databases:
            if database.alias == alias:
                return database
        return None
