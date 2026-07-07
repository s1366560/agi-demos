use super::support::*;

#[tokio::test]
async fn genes_are_tenant_scoped_slug_ordered_and_exclude_installed() {
    let Some(pool) =
        pool_or_skip("genes_are_tenant_scoped_slug_ordered_and_exclude_installed").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_gene_rows(&pool).await;

    seed_gene_user(&pool, "gene_user", false).await;
    seed_gene_tenant(&pool, "gene_tenant_a").await;
    seed_gene_tenant(&pool, "gene_tenant_b").await;
    seed_gene_membership(
        &pool,
        "gene_membership_a",
        "gene_user",
        "gene_tenant_a",
        ts(2026, 4, 1, 0, 0, 0),
    )
    .await;
    seed_gene_membership(
        &pool,
        "gene_membership_b",
        "gene_user",
        "gene_tenant_b",
        ts(2026, 4, 2, 0, 0, 0),
    )
    .await;
    seed_gene_instance(&pool, "gene_instance_a", "gene_tenant_a").await;

    seed_gene_record(
        &pool,
        SeedGene {
            id: "gene_global_review",
            slug: "review",
            tenant_id: None,
            created_at: ts(2026, 4, 3, 0, 0, 0),
            is_published: true,
            visibility: "public",
            deleted: false,
        },
    )
    .await;
    seed_gene_record(
        &pool,
        SeedGene {
            id: "gene_local_review",
            slug: "review",
            tenant_id: Some("gene_tenant_a"),
            created_at: ts(2026, 4, 4, 0, 0, 0),
            is_published: false,
            visibility: "org_private",
            deleted: false,
        },
    )
    .await;
    seed_gene_record(
        &pool,
        SeedGene {
            id: "gene_global_ops",
            slug: "ops",
            tenant_id: None,
            created_at: ts(2026, 4, 5, 0, 0, 0),
            is_published: true,
            visibility: "public",
            deleted: false,
        },
    )
    .await;
    seed_gene_record(
        &pool,
        SeedGene {
            id: "gene_hidden_global",
            slug: "hidden",
            tenant_id: None,
            created_at: ts(2026, 4, 6, 0, 0, 0),
            is_published: false,
            visibility: "public",
            deleted: false,
        },
    )
    .await;
    seed_gene_record(
        &pool,
        SeedGene {
            id: "gene_other_tenant",
            slug: "other",
            tenant_id: Some("gene_tenant_b"),
            created_at: ts(2026, 4, 7, 0, 0, 0),
            is_published: false,
            visibility: "org_private",
            deleted: false,
        },
    )
    .await;
    seed_gene_record(
        &pool,
        SeedGene {
            id: "gene_deleted",
            slug: "deleted",
            tenant_id: Some("gene_tenant_a"),
            created_at: ts(2026, 4, 8, 0, 0, 0),
            is_published: true,
            visibility: "public",
            deleted: true,
        },
    )
    .await;
    seed_installed_gene(
        &pool,
        "gene_installed_ops",
        "gene_instance_a",
        "gene_global_ops",
    )
    .await;
    seed_genome_record(
        &pool,
        SeedGenome {
            id: "gene_genome_global_stack",
            slug: "global-stack",
            tenant_id: None,
            created_at: ts(2026, 4, 11, 0, 0, 0),
            is_published: true,
            visibility: "public",
            deleted: false,
        },
    )
    .await;
    seed_genome_record(
        &pool,
        SeedGenome {
            id: "gene_genome_local_stack",
            slug: "local-stack",
            tenant_id: Some("gene_tenant_a"),
            created_at: ts(2026, 4, 12, 0, 0, 0),
            is_published: false,
            visibility: "org_private",
            deleted: false,
        },
    )
    .await;
    seed_genome_record(
        &pool,
        SeedGenome {
            id: "gene_genome_hidden",
            slug: "hidden-stack",
            tenant_id: None,
            created_at: ts(2026, 4, 13, 0, 0, 0),
            is_published: false,
            visibility: "public",
            deleted: false,
        },
    )
    .await;
    seed_genome_record(
        &pool,
        SeedGenome {
            id: "gene_genome_deleted",
            slug: "deleted-stack",
            tenant_id: Some("gene_tenant_a"),
            created_at: ts(2026, 4, 14, 0, 0, 0),
            is_published: true,
            visibility: "public",
            deleted: true,
        },
    )
    .await;

    let repo = PgGeneRepository::new(pool.clone());
    let tenant_id = repo
        .default_tenant_for_user("gene_user")
        .await
        .expect("default tenant query")
        .expect("user has tenant");
    assert_eq!(tenant_id, "gene_tenant_a");
    assert_eq!(
        repo.tenant_access_for_user("gene_user", "gene_tenant_a")
            .await
            .expect("tenant access query"),
        agistack_adapters_postgres::GeneTenantAccess::Allowed
    );
    assert_eq!(
        repo.tenant_access_for_user("gene_user", "gene_missing_tenant")
            .await
            .expect("missing tenant access query"),
        agistack_adapters_postgres::GeneTenantAccess::NotFound
    );

    let requested_slugs = vec!["ops".to_string(), "review".to_string()];
    let (records, total) = repo
        .list_genes(GeneListQuery {
            tenant_id: &tenant_id,
            include_global: true,
            category: None,
            search: None,
            slugs: &requested_slugs,
            visibility: None,
            is_published: None,
            exclude_installed_instance_id: None,
            limit: 10,
            offset: 0,
        })
        .await
        .expect("gene slug list succeeds");
    assert_eq!(total, 2);
    assert_eq!(
        records
            .iter()
            .map(|gene| gene.id.as_str())
            .collect::<Vec<_>>(),
        vec!["gene_global_ops", "gene_local_review"]
    );
    assert_eq!(records[1].tenant_id.as_deref(), Some("gene_tenant_a"));
    assert_eq!(records[0].manifest, json!({"tools": ["plan", "run"]}));

    let (records, total) = repo
        .list_genes(GeneListQuery {
            tenant_id: &tenant_id,
            include_global: true,
            category: None,
            search: None,
            slugs: &[],
            visibility: None,
            is_published: None,
            exclude_installed_instance_id: Some("gene_instance_a"),
            limit: 10,
            offset: 0,
        })
        .await
        .expect("exclude-installed gene list succeeds");
    assert_eq!(total, 2);
    assert_eq!(
        records
            .iter()
            .map(|gene| gene.id.as_str())
            .collect::<Vec<_>>(),
        vec!["gene_local_review", "gene_global_review"]
    );

    let detail = repo
        .get_gene("gene_local_review")
        .await
        .expect("gene detail query")
        .expect("gene detail exists");
    assert_eq!(detail.slug, "review");
    assert!(repo
        .get_gene("gene_deleted")
        .await
        .expect("deleted gene detail query")
        .is_none());

    let (genomes, total) = repo
        .list_genomes(GenomeListQuery {
            tenant_id: &tenant_id,
            include_global: true,
            search: None,
            visibility: None,
            is_published: None,
            limit: 10,
            offset: 0,
        })
        .await
        .expect("genome list succeeds");
    assert_eq!(total, 2);
    assert_eq!(
        genomes
            .iter()
            .map(|genome| genome.id.as_str())
            .collect::<Vec<_>>(),
        vec!["gene_genome_local_stack", "gene_genome_global_stack"]
    );
    assert_eq!(genomes[0].gene_slugs, vec!["review", "ops"]);
    assert_eq!(
        genomes[0].config_override,
        json!({"ops": {"mode": "strict"}})
    );

    let genome_detail = repo
        .get_genome("gene_genome_global_stack")
        .await
        .expect("genome detail query")
        .expect("genome detail exists");
    assert_eq!(genome_detail.slug, "global-stack");
    assert!(repo
        .get_genome("gene_genome_deleted")
        .await
        .expect("deleted genome detail query")
        .is_none());
}

async fn clean_gene_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM instance_genes WHERE id LIKE 'gene_%'")
        .execute(pool)
        .await
        .expect("clean instance genes");
    sqlx::query("DELETE FROM gene_market WHERE id LIKE 'gene_%'")
        .execute(pool)
        .await
        .expect("clean genes");
    sqlx::query("DELETE FROM genomes WHERE id LIKE 'gene_%'")
        .execute(pool)
        .await
        .expect("clean genomes");
    sqlx::query("DELETE FROM instances WHERE id LIKE 'gene_%'")
        .execute(pool)
        .await
        .expect("clean gene instances");
    sqlx::query("DELETE FROM user_tenants WHERE id LIKE 'gene_%'")
        .execute(pool)
        .await
        .expect("clean gene memberships");
    sqlx::query("DELETE FROM tenants WHERE id LIKE 'gene_%'")
        .execute(pool)
        .await
        .expect("clean gene tenants");
    sqlx::query("DELETE FROM users WHERE id LIKE 'gene_%'")
        .execute(pool)
        .await
        .expect("clean gene users");
}

async fn seed_gene_user(pool: &PgPool, user_id: &str, is_superuser: bool) {
    sqlx::query(
        "INSERT INTO users (id, email, is_active, is_superuser) VALUES ($1, $2, true, $3) \
         ON CONFLICT (id) DO UPDATE SET is_superuser = EXCLUDED.is_superuser",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .bind(is_superuser)
    .execute(pool)
    .await
    .expect("seed gene user");
}

async fn seed_gene_tenant(pool: &PgPool, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ($1, $2) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(tenant_id)
    .bind(format!("Tenant {tenant_id}"))
    .execute(pool)
    .await
    .expect("seed gene tenant");
}

async fn seed_gene_membership(
    pool: &PgPool,
    id: &str,
    user_id: &str,
    tenant_id: &str,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions, created_at) \
         VALUES ($1, $2, $3, 'member', $4, $5) \
         ON CONFLICT (id) DO UPDATE SET created_at = EXCLUDED.created_at",
    )
    .bind(id)
    .bind(user_id)
    .bind(tenant_id)
    .bind(json!({}))
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed gene membership");
}

async fn seed_gene_instance(pool: &PgPool, instance_id: &str, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO instances (id, name, slug, tenant_id, created_at, deleted_at) \
         VALUES ($1, $2, $3, $4, $5, NULL) \
         ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id, deleted_at = NULL",
    )
    .bind(instance_id)
    .bind(format!("Instance {instance_id}"))
    .bind(instance_id)
    .bind(tenant_id)
    .bind(ts(2026, 4, 1, 1, 0, 0))
    .execute(pool)
    .await
    .expect("seed gene instance");
}

struct SeedGene<'a> {
    id: &'a str,
    slug: &'a str,
    tenant_id: Option<&'a str>,
    created_at: DateTime<Utc>,
    is_published: bool,
    visibility: &'a str,
    deleted: bool,
}

async fn seed_gene_record(pool: &PgPool, gene: SeedGene<'_>) {
    let deleted_at = gene.deleted.then_some(gene.created_at);
    sqlx::query(
        "INSERT INTO gene_market \
         (id, name, slug, tenant_id, description, short_description, category, tags, source, \
          source_ref, icon, version, manifest, dependencies, synergies, install_count, \
          avg_rating, effectiveness_score, is_featured, review_status, is_published, \
          visibility, created_by, created_at, updated_at, deleted_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'official', $9, $10, '1.0.0', \
                 $11, $12, $13, 42, 4.5, 0.8, true, 'approved', $14, $15, $16, $17, $18, $19) \
         ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id, \
             created_at = EXCLUDED.created_at, deleted_at = EXCLUDED.deleted_at",
    )
    .bind(gene.id)
    .bind(format!("Gene {}", gene.slug))
    .bind(gene.slug)
    .bind(gene.tenant_id)
    .bind("Useful automation gene")
    .bind("Automation")
    .bind("automation")
    .bind(json!(["automation", "ops"]))
    .bind("https://example.test/genes")
    .bind("spark")
    .bind(json!({"tools": ["plan", "run"]}))
    .bind(json!(["base"]))
    .bind(json!(["review"]))
    .bind(gene.is_published)
    .bind(gene.visibility)
    .bind("gene_user")
    .bind(gene.created_at)
    .bind(ts(2026, 4, 9, 0, 0, 0))
    .bind(deleted_at)
    .execute(pool)
    .await
    .expect("seed gene record");
}

struct SeedGenome<'a> {
    id: &'a str,
    slug: &'a str,
    tenant_id: Option<&'a str>,
    created_at: DateTime<Utc>,
    is_published: bool,
    visibility: &'a str,
    deleted: bool,
}

async fn seed_genome_record(pool: &PgPool, genome: SeedGenome<'_>) {
    let deleted_at = genome.deleted.then_some(genome.created_at);
    sqlx::query(
        "INSERT INTO genomes \
         (id, name, slug, tenant_id, description, short_description, icon, gene_slugs, \
          config_override, install_count, avg_rating, is_featured, is_published, visibility, \
          created_by, created_at, updated_at, deleted_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 15, 4.7, false, $10, $11, $12, $13, $14, $15) \
         ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id, \
             created_at = EXCLUDED.created_at, deleted_at = EXCLUDED.deleted_at",
    )
    .bind(genome.id)
    .bind(format!("Genome {}", genome.slug))
    .bind(genome.slug)
    .bind(genome.tenant_id)
    .bind("Curated automation genome")
    .bind("Curated automation")
    .bind("bundle")
    .bind(json!(["review", "ops"]))
    .bind(json!({"ops": {"mode": "strict"}}))
    .bind(genome.is_published)
    .bind(genome.visibility)
    .bind("gene_user")
    .bind(genome.created_at)
    .bind(ts(2026, 4, 15, 0, 0, 0))
    .bind(deleted_at)
    .execute(pool)
    .await
    .expect("seed genome record");
}

async fn seed_installed_gene(pool: &PgPool, id: &str, instance_id: &str, gene_id: &str) {
    sqlx::query(
        "INSERT INTO instance_genes \
         (id, instance_id, gene_id, status, installed_version, config_snapshot, created_at, deleted_at) \
         VALUES ($1, $2, $3, 'installed', '1.0.0', $4, $5, NULL) \
         ON CONFLICT (id) DO UPDATE SET deleted_at = NULL",
    )
    .bind(id)
    .bind(instance_id)
    .bind(gene_id)
    .bind(json!({}))
    .bind(ts(2026, 4, 10, 0, 0, 0))
    .execute(pool)
    .await
    .expect("seed installed gene");
}
