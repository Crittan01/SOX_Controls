SELECT 
    event_time,
    session_server_principal_name,
    target_server_principal_name,
    server_instance_name,
    database_name,
    object_name,
    statement,
    file_name
FROM ADMONBD.SOX_EstadisticasSQLSERVER
WHERE 
    statement LIKE '%CREATE USER%' 
    AND TRUNC(event_time) BETWEEN ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -2) + 1 
                              AND LAST_DAY(ADD_MONTHS(SYSDATE, -1))
ORDER BY event_time DESC;