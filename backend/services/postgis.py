import os
from typing import Any

import psycopg
from psycopg.rows import dict_row


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "GeoPilot")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

TABLE_NAME = "public.tata_ev_charging_stations"


def get_connection():
    """Create a PostgreSQL connection using environment variables."""
    return psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        row_factory=dict_row,
    )


def test_postgis_connection() -> dict[str, Any]:
    """Verify PostgreSQL connectivity and PostGIS availability."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database() AS database_name,
                    current_user AS database_user,
                    version() AS postgres_version,
                    PostGIS_Full_Version() AS postgis_version
                """
            )
            result = cursor.fetchone()

    return {
        "connected": True,
        "database": result["database_name"],
        "user": result["database_user"],
        "postgres_version": result["postgres_version"],
        "postgis_version": result["postgis_version"],
    }


def find_nearby_chargers(
    latitude: float,
    longitude: float,
    radius_km: float = 10.0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find Tata EV chargers within radius_km using PostGIS."""
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")

    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")

    if radius_km <= 0:
        raise ValueError("radius_km must be greater than zero.")

    if limit <= 0:
        raise ValueError("limit must be greater than zero.")

    query = f"""
        WITH reference_point AS (
            SELECT ST_SetSRID(
                ST_MakePoint(%s, %s),
                4326
            )::geography AS geom
        )
        SELECT
            s.id,
            s.uid,
            s.region,
            s.city,
            s.state,
            s.country,
            s.name,
            s.address,
            s.latitude,
            s.longitude,
            s.pincode,
            s."chargerType" AS "chargerType",
            s."appName" AS "appName",
            s."cpoName" AS "cpoName",
            s."customerCategory" AS "customerCategory",
            s."megaChargers" AS "megaChargers",
            ROUND(
                (
                    ST_Distance(
                        s.geom::geography,
                        r.geom
                    ) / 1000.0
                )::numeric,
                3
            )::double precision AS distance_km
        FROM {TABLE_NAME} AS s
        CROSS JOIN reference_point AS r
        WHERE ST_DWithin(
            s.geom::geography,
            r.geom,
            %s * 1000.0
        )
        ORDER BY ST_Distance(
            s.geom::geography,
            r.geom
        )
        LIMIT %s
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    longitude,
                    latitude,
                    radius_km,
                    limit,
                ),
            )
            rows = cursor.fetchall()

    return [dict(row) for row in rows]
