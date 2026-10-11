# Corrección de cobertura documental

El usuario aportó tres fuentes ausentes del piloto anterior: resultados de admisión y padrón de ingeniería en Scribd, y un padrón en College Sidekick. El agente examinó las vistas públicas mediante navegación propia, una capacidad excluida del piloto anterior.

## Observaciones

- [Admisión UNT 2023-II](https://es.scribd.com/document/633704755/2023-II-Trujillo-1): la página impresa 22 muestra el nombre con apellidos primero en la fila correspondiente a Sistemas.
- [Padrón de ingeniería](https://es.scribd.com/document/709130194/7-Padron-Mesas-17-18-19-20-21-22-Ingenieria): se encontró el nombre con apellidos primero en la sección de ingeniería. Se registró una mención documental sin inferir participación efectiva ni postura política.
- [College Sidekick](https://www.collegesidekick.com/study-docs/23105577): el título coincide con un padrón de ingeniería; la vista pública disponible no mostró la fila del nombre. Posteriormente Tavily devolvió el enlace exacto con el nombre en su fragmento. La mención en el buscador y la fila no verificada en la vista accesible son observaciones distintas.

## Causas y cambios

El buscador usaba el nombre en el orden del formulario y una combinación literal con la universidad. Una fila con apellidos primero podía ser descartada. Las consultas documentales tampoco tenían un espacio reservado antes de variantes secundarias de correo o alias. Además, el lector opcional excluía plataformas como Scribd aunque encontrase el resultado, y el recorte inicial de texto podía dejar fuera filas de documentos largos.

La mejora reserva una consulta documental dentro del presupuesto habitual, busca frases completas con una alternativa de orden, reconoce las plataformas, registra razones de rechazo y permite conservar extractos centrados en el nombre dentro del contenido público descargado. Los enlaces de plantilla se eliminan antes de extraer enlaces del contenido.

## Prueba real

Se ejecutó `SearchDorkerTool` con la configuración actual y un presupuesto de dos consultas: nombre completo general y consulta documental con dos órdenes de nombre y filtro de dominios. Tavily consumió dos créditos declarados por el proveedor. La consulta documental devolvió cuatro resultados; dos pasaron el filtro de frase completa y dos se rechazaron por falta de evidencia literal. Los aceptados fueron College Sidekick y [otro documento de Scribd, T2023-I](https://es.scribd.com/document/633081759/T2023-I). Este último sigue siendo una mención candidata, sin inspección completa ni atribución personal automática.

La prueba demuestra recuperación adicional concreta, sin garantizar todos los resultados de Google. En esa consulta Tavily no devolvió como hallazgos aceptados los dos Scribd originales; estos se verificaron mediante navegación propia. Ningún proveedor ni filtro ofrece cobertura exhaustiva.

Las notas, fuentes y métodos quedaron en un [expediente documental nuevo](http://localhost:3000/investigation/af90958c-0c65-4cda-a66b-05d9f6ce9296), separado del piloto comparativo. La prueba directa de la herramienta y la navegación externa se declaran fuera de la traza de ejecuciones MCP. No se modificaron los expedientes ni métricas del piloto.

El informe omite códigos de matrícula, DNI y datos de otras personas. Los cambios afectan al buscador y lector compartidos: benefician reglas y MCP. Para probar el beneficio adicional del navegador del agente, debe añadirse una condición experimental explícita con revisión independiente.
