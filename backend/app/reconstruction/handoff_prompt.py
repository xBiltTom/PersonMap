"""Shared handoff text for the web UI and the local Codex launcher."""
from uuid import UUID


def reconstruction_prompt(request_id):
    request_id = UUID(str(request_id))
    return (
        f'Completa en PersonMap la solicitud de reconstrucción {request_id}. '
        'Usa el servidor MCP personmap: lee get_reconstruction_request, reclama con claim_reconstruction_request '
        '(client=Codex y tu modelo real si lo conoces) y conserva el claim_token sin incluirlo en notas. '
        'El consentimiento y el alcance están registrados en el expediente. '
        'Pagina list_public_posts del investigation_id recibido, contrasta cada texto y lee las imágenes '
        'con read_post_images, incluidos recortes si el texto no es legible. '
        'No modifiques el conjunto de entrada durante esta solicitud. '
        'Analiza todas las publicaciones, ordena por exposición y reconstruye la identidad con citas. '
        'Distingue observaciones, inferencias y límites de atribución; evita exagerar el riesgo. '
        'Informa avances con update_reconstruction_progress. '
        'Finalmente usa submit_reconstruction_result con el request_id, claim_token y el resultado estructurado '
        'según el contrato devuelto por get_reconstruction_request. No basta con escribir la respuesta en el chat '
        'ni guardar una nota: la web está esperando ese envío. '
        'Si una fuente no se puede leer, declara el límite y la cobertura parcial. '
        'Si no puedes completar el trabajo, informa failed=true con update_reconstruction_progress.'
    )


def reconstruction_command(request_id):
    return ('backend/.venv/bin/python backend/scripts/personmap_mcp.py codex '
            f'--reconstruction-request {UUID(str(request_id))}')
