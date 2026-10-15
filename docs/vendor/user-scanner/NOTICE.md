# user-scanner: referencias seleccionadas

Copyright (c) 2025 Kaif. Licencia [MIT](LICENSE).

Person Map adapta referencias de petición/endpoint para GitHub, Adobe y
Atlassian del commit `38ce09e32375a6072d38962d1268170583ad25df` de
[kaifcodec/user-scanner](https://github.com/kaifcodec/user-scanner).
Los archivos originales y sus hashes están en [provenance.json](provenance.json).
No se instala ni ejecuta el paquete. Los cambios están en
`backend/app/tools/email_catalog.py` y `email_enumerator.py`, junto a las
técnicas de Holehe con su propia atribución GPL-3.0.

La adaptación añade interpretación estricta de esquemas, disponibilidad
explícita en GitHub, métodos SSO de Adobe y controles aleatorios independientes.
La acción `social_login` de Atlassian se observó en la prueba de Person Map;
no se toma de una regla genérica que acepte cualquier respuesta de login.

ORCID usa el contrato público `registerEmailValidate.json`, revisado en
[RegistrationController.java de ORCID](https://github.com/ORCID/ORCID-Source/blob/main/orcid-web/src/main/java/org/orcid/frontend/web/controllers/RegistrationController.java).
Miro usa la validación de correo observada en su cliente público de registro,
build `auth-ICihi__yo2WUdxvRPLvpz`. No se incorpora código de sus clientes:
se implementan peticiones y parsers propios. Miro produce solo una pista de
autenticación, sin inferir registro; la validación de ORCID puede estar bloqueada.
