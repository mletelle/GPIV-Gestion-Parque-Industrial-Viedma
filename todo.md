Need to fix:
fíjate en la parte de detalle del proyecto que está desordenado. Hay cosas que están más arriba, más abajo, te permite poner valor negativo. Necesitas el metro cuadrados, te permite poner también valor negativo. En varios lugares te dejan poner valores negativos.
Después, bueno, no entiendo por qué residuos es un campo de texto cuando debería ser un sí no, creo yo, no entiendo. Después, en energía está perfecto, por ahí en potencia debería ser un poco más estimativo. Yo lo que es consumo y eso lo pondría en estimativo, ¿viste? Porque es estimado, estimado, entonces pondría entre cero y tanto, entre tanto y dos veces tanto, y así entre intervalos pondría a las necesidades. Después, necesidad de metros cuadrados, está bien. Está bien. Después, tipo de empresa nueva o existente, está bien, por ahí un poco raro. Después, rubro podría ampliarse aún más. Objetivo del proyecto podría revisarse un poquito más.

Después, cuando entro como proveedor, quiero que año de período esté por defecto en este mes y mes de período esté por defecto en este mes. Fíjate que hay un problema de seguridad gravísimo, que se llama proveedor agua, proveedor luz, proveedor gas, pero como proveedor de agua puedo decretar el gas o la electricidad del otro. Y como proveedor de luz puedo decretar el agua o el gas. Está mal eso. No tendría que ser dejar en blanco los servicios que no aplican. Tendría que validar proveedor de qué estoy. O sea, debería modificarse lo suficiente para que quede escrito proveedor de qué es y para que pueda solamente registrar un consumo. Y que no muestre el resto, que no muestre los que no aplica. Si es agua, que muestre agua potable y agua cruda y no muestre electricidad ni gas. Si es electricidad, que no muestre los otros tres. y así.

Después tengo un problema con el catálogo, el catálogo público. No sé para qué existe. No entiendo para qué, si la administración, que es el que maneja los lotes, tiene su catálogo. Para mí habría que, no sé, borrarlo o por lo menos que vos me expliques para qué sirve el catálogo público, por qué lo tenés ahí, por qué lo mantenés. No sé para qué me sirve tener lotes disponibles, las parcelas del parque, qué sé yo, y el detalle. Si ya el administrador tiene cierta... cierto registro de las parcelas y todos los detalles porque puede gestionar lotes, que es exactamente lo mismo que el catálogo público. No me gusta el catálogo público.

Después, el usuario de municipio o el usuario de organismos públicos debería tener un dashboard más parecido al que tiene el administrador, con muchos más KPIs. O sea, tiene solamente empresas activas y lotes ocupados. Podría tener un dashboard con consumos, con bla, bla, bla, con un montón de cosas, no solo lo que tiene actualmente. Podría tener un dashboard mucho más inteligente, mucho más interesante. O sea, podrías investigar y proponerme ideas de los diferentes tipos de dashboards que se pueden hacer, ¿no? Entonces, qué KPIs, qué indicadores, etcétera, etcétera, etcétera.

Después, la empresa Alfa, Alfa Alimentos, yo entro y está roto el HTML. Hay que revisar el HTML porque está roto. Muestra un par de datos de contacto, pero está roto. Entonces me faltaría un par de cositas ahí de revisar, ¿viste? El sistema es lindo, porque está roto y no puedo hacer nada interesante. Si está roto, se ve todo feo, todo roto.

Después, la empresa Beta, empresa Beta Tech, tiene un problema. Primero dijo que la anterior está roto, tiene llaves en los nombres y cosas por el estilo. pero después, en el historial de estado, no muestra la enviada de solicitud y después el preaprobado. Muestra una sola cosa, pero bueno, podría revisarse eso.

Después, en la pantalla de administración, en el inicio yo quiero solo reportes y accesos rápidos. No quiero la parte de indicadores de parques. O sea, no quiero la parte del dashboard de control en el inicio. Quiero que eso quede en consulta del parque, no, en... No, que lo saques de ahí. Que saques eso de ahí y lo pongas en consulta del parque y consulta del parque se llame dashboard. Y bueno, lo mismo que los KPIs que te había dicho antes. O sea, que tenga más KPIs más copados, que compartan los mismos KPIs que gobierno, que tenga, además de ocupación del parque, lote disponible, consumo, que tenga otros más. Que tenga cosas más copadas. Ahí proponeme una idea de con más gráficos, con más diseño, con más cosas. Proponeme más ideas para el dashboard. Pero bueno, principalmente sacalo de inicio al dashboard y a los indicadores del parque y ponelo en consulta del parque y a consulta del parque renombralo dashboard. Después hay otro problema. En caso de que yo borre toda la URL, estando registrado, ¿no? Estando como admin del repab. En caso de que yo borre toda la URL y entre, me lleva a la landing. Yo no debería poder acceder a la landing si ya estoy como admin o como algún usuario. Si yo ya estoy registrado como usuario y quiero entrar a la landing, me debería automáticamente redirigir al inicio, no a la landing. Entonces, habría que revisar eso.

que carajos es Parcela 999 En Uso 1000,00 m²???? de donde verga salio?

como proveeedor al querer entrar a consumos, tira "403 Forbidden"

Hay un problema, porque las migraciones no se hacen automáticamente cuando yo hago docker down, docker up. Yo recuerdo que hay gente que arma el Docker file de tal manera que en el que le anda el contenedor, bla, bla, bla, y hace docker down, docker up y se cargan todas las migraciones. Creo que como que se automatizan el migrations, make migrations, hacer migraciones, todo eso se automatiza. ¿Cómo se puede hacer esto?

actualmente el inicio/dashboard esta roto/vacio:
"
Indicadores del parque
Ocupación del parque
%

de lotes ocupados
Lotes disponibles

para asignar a nuevas empresas
Consumo último período
Sin datos

No hay consumos cargados todavía
Empresas activas

radicadas, en obra, finalizadas o escrituradas
"
creo que ya esta fix:
Migración genera_residuos
Form solicitud: orden, min=0, residuos Si/No
Fix mi_solicitud.html roto
-------------------
Despues, funcionalidades a agregar/pensar/planear/no implementar aun:
-
Optimizar registro de empresas ya existentes, vincular lote y usuario
Actualmente, el proceso de alta para empresas requiere completar mucha información, incluso cuando la empresa ya existe en el sistema. Se solicita simplificar este flujo, no volver a pedir toda la información redundante. Solo solicitar vinculación de la nueva cuenta de usuario con la empresa existente y seleccionar el lote correspondiente. Una vez realizado esto, finalizar el proceso sin campos extra innecesarios (dirección, teléfono, etc.), ya que esos datos ya están cargados.
-
Mejorar flujo de login y acceso diferenciado por tipo de usuario 
Se requiere implementar mejoras en el sistema de login para que el usuario seleccione su rol al ingresar al sistema tenga las opciones de Empresa, Organismo Público o Proveedor.
Si elige "Empresa": debe poder cargar solicitudes inmediatamente tras el login.
Si elige "Proveedor" u "Organismo Público": requerir un proceso de verificación/autorización y adjuntar documentación antes de operar como proveedor o gobierno.
-
Implementar una ticketera de comunicación entre empresa, proveedor, organismo público con la administración 
Se requiere desarrollar un sistema de tickets (ticketera) de comunicación para mejorar la interacción entre los distintos perfiles del sistema. El sistema permitirá abrir tickets entre los actores mencionados y la administracion para consultas, solicitudes, soporte, avisos, incidencias, etc.
-
Permitir múltiples usuarios por empresa y traslado de titularidad entre usuarios
Actualmente, solo se permite asociar un único usuario por empresa. Es necesario implementar la funcionalidad que rmita que una empresa tenga más de un usuario asociado y permita que la titularidad de la empresa (el usuario principal) se pueda trasladar a otro usuario dentro de la misma empresa.
Esto implica ajustes en la lógica de asociaciones entre usuarios y empresas, así como en la gestión de roles y permisos. Además, deberá implementarse una interfaz para que un usuario con permisos de titular pueda transferir fácilmente la titularidad a otro usuario de la empresa.
-
Registro de Documentos Publicos
Para guardar las decisiones de los directores y registrar la entrega de lotes.
Vincular con expedientes.
Guarda las actas de los jefes.
-
