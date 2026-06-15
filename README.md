# GPIV — Gestion del Parque Industrial de Viedma

Sistema web para la administracion integral del Parque Industrial de Viedma. 

Proyecto académico de **Tivena** para la materia *Ingenieria de Software* — UNRN, cursada 2026.

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
| `miembro_delta_1` | _(equipo de Delta)_              | —               | —       | — |
| `empresa_epsilon` | Epsilon Construcciones S.A.      | En Construcción | 029     | +18 dias    |
| `miembro_epsilon_1` | _(equipo de Epsilon)_          | —               | —       | — |
| `miembro_epsilon_2` | _(equipo de Epsilon)_          | —               | —       | — |
| `empresa_zeta`    | Zeta Metalurgica S.A.            | En Construcción | 030     | +7 dias     |
| `empresa_eta`     | Eta Logistica S.R.L.             | Finalizado      | 036     | +60 dias    |
| `empresa_pix`   | Pix Alimentos del Sur S.A.     | Finalizado      | 006     | +90 dias    |
| _(sin usuario)_   | Fundidora del Atlantico S.A.     | Escriturado     | 015     | —           |
| _(sin usuario)_   | Molinos Patagonicos S.R.L.       | Escriturado     | 007     | —           |

Las dos empresas "historicas" (ya escrituradas hace años) no traen
usuario de portal.

#### Colaboradores libres (para probar el flujo de invitación Mi Equipo)

| Usuario             | Empresa asignada | Notas                                  |
| :---                | :---             | :---                                   |
| `empresa_libre_1`   | ninguna          | Pedro Martínez; invitable por cualquier Titular |
| `empresa_libre_2`   | ninguna          | Ana Rodríguez; invitable por cualquier Titular  |

Para registrar un colaborador nuevo sin usar estas cuentas, acceder a Registro → Colaborador de empresa en el selector.

---


## Equipo

Proyecto hecho por Tivena, para Ingenieria de Software, UNRN 2026

- Choque Lopez, Andres
- Letelle, Mauro
- Perisse, Lautaro
- Argel, Ramiro

---
