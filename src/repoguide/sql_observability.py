"""SQLAlchemy query-level timings as child MLflow spans (no bound values)."""
from __future__ import annotations
from sqlalchemy import event
import hashlib
from repoguide.telemetry import record, span


def instrument_engine(engine):
    @event.listens_for(engine, 'before_cursor_execute')
    def before(conn, cursor, statement, parameters, context, executemany):
        operation=statement.lstrip().split(None,1)[0].upper() if statement.strip() else 'SQL'
        # Never log literal parameter values, including credentials or code.
        context._repoguide_trace_cm=span('db.sql','TOOL',{'operation':operation, 'statement_sha256':hashlib.sha256(statement.encode()).hexdigest()[:16]},{'db.system':'postgresql','db.executemany':executemany})
        context._repoguide_trace_span=context._repoguide_trace_cm.__enter__()

    @event.listens_for(engine, 'after_cursor_execute')
    def after(conn,cursor,statement,parameters,context,executemany):
        cm=getattr(context,'_repoguide_trace_cm',None)
        if cm is not None:
            record(getattr(context,'_repoguide_trace_span',None), {'rowcount':cursor.rowcount}, db_rowcount=cursor.rowcount)
            cm.__exit__(None,None,None)

    @event.listens_for(engine, 'handle_error')
    def on_error(exception_context):
        ctx=exception_context.execution_context
        if ctx is not None:
            cm=getattr(ctx,'_repoguide_trace_cm',None)
            if cm:
                cm.__exit__(type(exception_context.original_exception),exception_context.original_exception,exception_context.original_exception.__traceback__)
