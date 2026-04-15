# GPIV — Gestion del Parque Industrial de Viedma

Sistema web para la administracion integral del Parque Industrial de Viedma. 

Proyecto académico **Tivena** para la materia *Ingenieria de Software* — UNRN, cursada 2026.

<div align="center">
  <img src="assets/tivena.png" alt="Tivena" width="160">
</div>

---

## Contexto 

El Parque Industrial de Viedma se ubica sobre la Ruta Provincial Nº 1, camino a El Condor (Viedma, Rio Negro). Administrado por **ENREPAVI**, cuenta con 65 parcelas sobre una superficie administrable de 184.047 m2. Actualmente alberga 52 empresas activas en rubros como construccion, frigorifico, secaderos de fruta, talleres mecánicos y logistica.

El sistema reemplaza el seguimiento manual por planillas y comunicacion informal, centralizando todas las operaciones del parque en una única plataforma web.

---

## Stack tecnologico

| Componente | Tecnologia | Componente | Tecnologia |
| :--- | :--- | :--- | :--- |
| Backend | Django + Python  | Base de datos | PostgreSQL  |
| Frontend | Bootstrap  | Servidor | Gunicorn + Whitenoise |
| Infraestructura | Docker | Despliegue | Oracle Cloud Free Tier  |


---

## Funcionalidades

- Portal público sin login: info del parque, catálogo de lotes, formulario de solicitud de radicacion
- Flujo de radicacion:
  - Pre evaluacion y aprobacion de solicitudes por la administracion
  - Adjudicacion de lote y alerta de compatibilidad industrial entre parcelas vecinas
  - Seguimiento de avance constructivo (carga por empresa, validacion por administracion)
  - Solicitudes de prorroga
  - finalizacion de obra y registro de escrituracion
  - baja administrativa con liberacion del lote asignado
- paneles condicionales por rol: cada grupo ve solo lo que le corresponde
- notificaciones automaticas de vencimiento de plazos por mail
- caducidad automatica de proyectos con plazo vencido


### Roles del sistema

| Grupo | Acceso |
| :--- | :--- |
| `ADMIN_ENREPAVI` | Gestion completa: evaluar solicitudes, adjudicar lotes, validar avances, aprobar prorrogas, emitir bajas, escriturar |
| `EMPRESA` | Panel propio: estado de solicitud, lote asignado, carga de avances, solicitud de prorrogas |
| `PROVEEDOR_SERVICIOS` | Carga mensual de consumos (agua, electricidad, gas) por empresa |
| `ORGANISMO_PUBLICO` | Solo lectura: nomina de empresas radicadas e indicadores generales del parque |

---

## Instalacion y ejecucion local

### 1. Clonar el repo
git clone https://github.com/mletelle/GPIV-Gestion-Parque-Industrial-Viedma
cd GPIV-Gestion-Parque-Industrial-Viedma

### 2. Copiar variables de entorno
cp .env.example .env

### 3. Levantar los contenedores (aplica migraciones en el arranque)
docker compose up

### 4. En otra terminal: poblar parcelas, grupos, usuarios y empresas de prueba
docker compose exec web python manage.py cargar_datos_prueba


La app local queda en http://localhost:8000
La app desplegada en Oracle Cloud queda en http://gpiv.tivena.com.ar

El comando `cargar_datos_prueba` es idempotente: se puede volver a correr para resetear empresas, avances, prorrogas y consumos sin tocar las parcelas.


### Credenciales de desarrollo

Contraseña por defecto para todos los usuarios: `gpiv1234`
(el superuser `admin` usa `admin1234`).

#### Administracion

| Usuario            | Grupo             | Notas                   |
| :---               | :---              | :---                    |
| `admin`            | —                 | superuser Django        |
| `admin_enrepavi`   | ADMIN_ENREPAVI    | admin funcional         |

#### Proveedores de servicios

| Usuario             | Servicio       |
| :---                | :---           |
| `proveedor_agua`    | Agua           |
| `proveedor_luz`     | Electricidad   |
| `proveedor_gas`     | Gas            |

#### Organismos publicos

| Usuario                  | Organismo            |
| :---                     | :---                 |
| `organismo_municipal`    | Municipio de Viedma  |
| `organismo_provincial`   | Gobierno Rio Negro   |

#### Empresas de prueba (una por cada estado de la FSM)

| Usuario           | Razon social                     | Estado          | Parcela | Vencimiento |
| :---              | :---                             | :---            | :---    | :---        |
| `empresa_alfa`    | Alfa Alimentos S.A.              | En Evaluación   | —       | —           |
| `empresa_beta`    | Beta Tech S.R.L.                 | Pre-Aprobado    | —       | —           |
| `empresa_gamma`   | Gamma Quimica S.A.               | Rechazado       | —       | —           |
| `empresa_delta`   | Delta Servicios S.R.L.           | Radicada        | 024     | +180 dias   |
| `empresa_epsilon` | Epsilon Construcciones S.A.      | En Construcción | 029     | +18 dias    |
| `empresa_zeta`    | Zeta Metalurgica S.A.            | En Construcción | 030     | +7 dias     |
| `empresa_eta`     | Eta Logistica S.R.L.             | Finalizado      | 036     | +60 dias    |
| `empresa_theta`   | Theta Alimentos del Sur S.A.     | Finalizado      | 006     | +90 dias    |
| _(sin usuario)_   | Fundidora del Atlantico S.A.     | Escriturado     | 015     | —           |
| _(sin usuario)_   | Molinos Patagonicos S.R.L.       | Escriturado     | 007     | —           |

Las dos empresas "historicas" (ya escrituradas hace años) no traen
usuario de portal.

---


## Equipo

Proyecto hecho por Tivena, para Ingenieria de Software, UNRN 2026

- Choque Lopez, Andres
- Letelle, Mauro
- Perisse, Lautaro
- Argel, Ramiro

