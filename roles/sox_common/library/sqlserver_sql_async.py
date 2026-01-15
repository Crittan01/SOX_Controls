#!/usr/bin/python
# -*- coding: utf-8 -*-

DOCUMENTATION = '''
---
module: sqlserver_sql_async
short_description: Execute SQL Server queries with threading support
description:
    - Execute arbitrary SQL against a SQL Server database
    - Support for parallel execution of multiple SQL statements using threading
    - Compatible with pymssql library
version_added: "1.0.0"
options:
    username:
        description:
            - The database username to connect to the database
        required: true
        aliases: ['user']
    password:
        description:
            - The password to connect to the database
        required: true
    host:
        description:
            - The host of the database
        required: true
    port:
        description:
            - The port to connect to the database
        required: false
        default: 1433
        type: int
    database:
        description:
            - The database name to connect to
        required: false
        default: master
    instance:
        description:
            - SQL Server instance name
        required: false
    sql:
        description:
            - Single SQL statement to execute
        required: false
    sql_list:
        description:
            - List of SQL statements to execute in parallel
        required: false
        type: list
    max_workers:
        description:
            - Maximum number of parallel threads
        required: false
        default: 10
        type: int
    timeout:
        description:
            - Timeout in seconds for each SQL statement
        required: false
        default: 300
        type: int
notes:
    - pymssql needs to be installed
requirements: [ "pymssql" ]
author: Automation Team
'''

EXAMPLES = '''
# Execute single SQL
- sqlserver_sql_async:
    host: 10.205.24.153
    port: 1436
    instance: GIGA
    database: master
    username: SURASTAT
    password: secret
    sql: 'SELECT @@VERSION'

# Execute multiple queries in parallel
- sqlserver_sql_async:
    host: 10.205.24.153
    port: 1436
    username: SURASTAT
    password: secret
    database: master
    sql_list:
      - 'SELECT COUNT(*) FROM sys.databases'
      - 'SELECT name FROM sys.databases WHERE database_id > 4'
    max_workers: 20
    timeout: 300
'''

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from ansible.module_utils.basic import AnsibleModule

try:
    import pymssql
    pymssql_exists = True
except ImportError:
    pymssql_exists = False


class SQLServerConnectionManager:
    """Manages SQL Server connections for threading"""
    
    def __init__(self, connection_params):
        self.connection_params = connection_params
        
    def create_connection(self):
        """Create a new SQL Server connection"""
        host = self.connection_params.get('host')
        port = self.connection_params.get('port', 1433)
        user = self.connection_params.get('user')
        password = self.connection_params.get('password')
        database = self.connection_params.get('database', 'master')
        instance = self.connection_params.get('instance')
        timeout = self.connection_params.get('timeout', 300)
        
        try:
            # Build connection string
            server = f"{host}:{port}" if not instance else f"{host}\\{instance}"
            
            conn = pymssql.connect(
                server=server,
                user=user,
                password=password,
                database=database,
                timeout=timeout,
                login_timeout=30,
                as_dict=False
            )
            
            return conn
            
        except pymssql.Error as e:
            raise Exception(f'Could not connect to SQL Server: {str(e)}')


def execute_single_sql_thread(connection_manager, sql_statement, timeout, thread_index):
    """Execute a single SQL statement in a thread"""
    result = {
        'sql': sql_statement[:100] + '...' if len(sql_statement) > 100 else sql_statement,
        'full_sql': sql_statement,
        'success': False,
        'message': '',
        'error': None,
        'execution_time': 0,
        'thread_id': f'worker-{thread_index}',
        'thread_name': threading.current_thread().name
    }
    
    start_time = time.time()
    conn = None
    cursor = None
    
    try:
        # Create connection for this thread
        conn = connection_manager.create_connection()
        cursor = conn.cursor()
        
        # Execute the SQL
        sql_clean = sql_statement.strip().rstrip(';')
        
        cursor.execute(sql_clean)
        
        # Check if it's a SELECT query
        if sql_clean.upper().strip().startswith(('SELECT', 'WITH', 'EXEC', 'EXECUTE')):
            fetch_result = cursor.fetchall()
            result['message'] = fetch_result
            result['success'] = True
            result['row_count'] = len(fetch_result) if fetch_result else 0
            
            # Get column names
            if cursor.description:
                result['columns'] = [desc[0] for desc in cursor.description]
        else:
            # DML/DDL statement
            conn.commit()
            result['message'] = f'Statement executed successfully'
            result['success'] = True
            result['row_count'] = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
            
    except pymssql.Error as e:
        result['error'] = f'SQL Server Error: {str(e)}'
        result['success'] = False
        
    except Exception as e:
        result['error'] = f'General Error: {str(e)}'
        result['success'] = False
        
    finally:
        execution_time = time.time() - start_time
        result['execution_time'] = round(execution_time, 3)
        
        try:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        except:
            pass
            
    return result


def execute_sql_list_parallel(module, connection_params, sql_list, max_workers, timeout):
    """Execute multiple SQL statements in parallel using ThreadPoolExecutor"""
    
    if not sql_list or len(sql_list) == 0:
        return {
            'summary': {
                'total_statements': 0,
                'successful': 0,
                'failed': 0,
                'success_rate': 0,
                'total_execution_time': 0,
                'max_workers_used': 0,
                'average_time_per_statement': 0
            },
            'detailed_results': [],
            'failed_statements': [],
            'successful_statements': []
        }
    
    connection_manager = SQLServerConnectionManager(connection_params)
    results = []
    successful = 0
    failed = 0
    
    start_time = time.time()
    
    # Adjust max_workers based on list size
    if len(sql_list) < 100:
        actual_workers = min(10, max_workers)
    elif len(sql_list) < 500:
        actual_workers = min(15, max_workers)
    elif len(sql_list) < 1000:
        actual_workers = min(20, max_workers)
    elif len(sql_list) < 3000:
        actual_workers = min(30, max_workers)
    else:
        actual_workers = min(50, max_workers)

    try:
        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            future_to_sql = {
                executor.submit(execute_single_sql_thread, connection_manager, sql, timeout, i): (sql, i)
                for i, sql in enumerate(sql_list)
            }
            
            completed = 0
            for future in as_completed(future_to_sql, timeout=timeout*2):
                try:
                    result = future.result(timeout=timeout)
                    results.append(result)
                    completed += 1
                    
                    if result['success']:
                        successful += 1
                    else:
                        failed += 1
                        
                    if len(sql_list) > 50 and completed % 50 == 0:
                        module.log(f"Completed {completed}/{len(sql_list)} statements")
                        
                except Exception as exc:
                    sql, thread_idx = future_to_sql[future]
                    failed_result = {
                        'sql': sql[:100] + '...' if len(sql) > 100 else sql,
                        'full_sql': sql,
                        'success': False,
                        'message': f'Thread execution failed: {str(exc)}',
                        'error': str(exc),
                        'execution_time': 0,
                        'thread_id': f'worker-{thread_idx}',
                        'thread_name': 'failed'
                    }
                    results.append(failed_result)
                    failed += 1
                    completed += 1
                    
    except Exception as e:
        module.fail_json(msg=f"ThreadPoolExecutor failed: {str(e)}")
    
    total_time = time.time() - start_time
    
    # Sort results by original order
    try:
        results.sort(key=lambda x: int(x['thread_id'].split('-')[1]) if 'worker-' in x['thread_id'] else 999)
    except:
        pass
    
    summary = {
        'total_statements': len(sql_list),
        'successful': successful,
        'failed': failed,
        'success_rate': round((successful / len(sql_list)) * 100, 2) if len(sql_list) > 0 else 0,
        'total_execution_time': round(total_time, 2),
        'max_workers_used': actual_workers,
        'average_time_per_statement': round(total_time / len(sql_list), 3) if len(sql_list) > 0 else 0,
        'theoretical_sequential_time': round(sum(r['execution_time'] for r in results), 2),
        'speedup_factor': round(sum(r['execution_time'] for r in results) / total_time, 2) if total_time > 0 else 0
    }
    
    return {
        'summary': summary,
        'detailed_results': results,
        'failed_statements': [r for r in results if not r['success']],
        'successful_statements': [r for r in results if r['success']]
    }


def execute_single_sql_sync(module, connection_params, sql):
    """Execute single SQL statement synchronously"""
    connection_manager = SQLServerConnectionManager(connection_params)
    
    try:
        conn = connection_manager.create_connection()
        cursor = conn.cursor()
        
        sql_clean = sql.strip().rstrip(';')
        first_word = sql_clean.split(None, 1)[0].upper() if sql_clean else ''
        
        cursor.execute(sql_clean)
        
        if first_word in ('SELECT', 'WITH', 'EXEC', 'EXECUTE', 'SHOW'):
            result = cursor.fetchall()
            cursor.close()
            conn.close()
            return result
        else:
            conn.commit()
            cursor.close()
            conn.close()
            return f'SQL executed successfully: {sql_clean[:50]}...'
            
    except pymssql.Error as e:
        module.fail_json(msg=f'SQL Server Error: {str(e)}', changed=False)
    except Exception as e:
        module.fail_json(msg=f'Error: {str(e)}', changed=False)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            user=dict(required=True, aliases=['username']),
            password=dict(required=True, no_log=True),
            host=dict(required=True),
            port=dict(required=False, default=1433, type='int'),
            database=dict(required=False, default='master'),
            instance=dict(required=False, default=None),
            sql=dict(required=False),
            sql_list=dict(required=False, type='list'),
            max_workers=dict(required=False, default=10, type='int'),
            timeout=dict(required=False, default=300, type='int'),
        ),
        mutually_exclusive=[['sql', 'sql_list']],
        required_one_of=[['sql', 'sql_list']]
    )

    if not pymssql_exists:
        module.fail_json(msg="The pymssql module is required. Install with: pip install pymssql")

    connection_params = {
        'user': module.params["user"],
        'password': module.params["password"],
        'host': module.params["host"],
        'port': module.params["port"],
        'database': module.params["database"],
        'instance': module.params["instance"],
        'timeout': module.params["timeout"]
    }
    
    sql = module.params["sql"]
    sql_list = module.params["sql_list"]
    max_workers = module.params["max_workers"]
    timeout = module.params["timeout"]

    if max_workers < 1:
        max_workers = 1
    elif max_workers > 50:
        max_workers = 50

    if sql:
        result = execute_single_sql_sync(module, connection_params, sql)
        sql_clean = sql.strip().rstrip(';')
        first_word = sql_clean.split(None, 1)[0].upper() if sql_clean else ''

        if first_word in ('SELECT', 'WITH', 'EXEC', 'EXECUTE', 'SHOW'):
            module.exit_json(msg=result, changed=False)
        else:
            module.exit_json(msg=result, changed=True)
            
    elif sql_list:
        if len(sql_list) == 0:
            module.fail_json(msg="sql_list cannot be empty")
            
        result = execute_sql_list_parallel(module, connection_params, sql_list, max_workers, timeout)
        
        changed = any(
            not r['full_sql'].upper().strip().startswith(('SELECT', 'WITH', 'SHOW'))
            for r in result['successful_statements']
        )
        
        module.exit_json(
            msg=result,
            changed=changed,
            summary=result['summary'],
            failed_count=result['summary']['failed'],
            successful_count=result['summary']['successful']
        )
    
    module.fail_json(msg="No SQL provided")


if __name__ == '__main__':
    main()