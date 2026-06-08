def inserir(supabase, audit_log):
    return supabase.table("audit_logs").insert(audit_log).execute()
