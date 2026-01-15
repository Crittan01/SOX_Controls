SELECT  
    event_time,
    action_id,  
    class_type,
    session_server_principal_name, 
    target_server_principal_name, 
    server_instance_name, 
    database_name, 
    object_name, 
    statement, 
    file_name
FROM sys.fn_get_audit_file('J:\Auditoria_giga_giga\*.sqlaudit', DEFAULT, DEFAULT) 
WHERE 
    event_time >= CAST(GETDATE() - 1 AS DATE) 
    AND event_time < CAST(GETDATE() AS DATE)
    AND action_id IN ('CR','LGDB','LGLG','PWPL','LGDA','LGEA',
                      'PWEX','DR','LGNM','AL','G','D','APRL','DPRL')
ORDER BY event_time DESC;