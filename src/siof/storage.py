from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .models import Artifact, DataNode, EnergyRun, Finding, IntentRecord, TransformEdge


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                hash TEXT NOT NULL,
                parse_ok INTEGER NOT NULL,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                module TEXT NOT NULL,
                kind TEXT NOT NULL,
                location TEXT NOT NULL,
                UNIQUE(symbol, module, location)
            );

            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                transform_symbol TEXT NOT NULL,
                transform_kind TEXT NOT NULL,
                location TEXT NOT NULL,
                confidence REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY,
                rule_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                file_path TEXT NOT NULL,
                line INTEGER NOT NULL,
                message TEXT NOT NULL,
                autofix_applied INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS intent_records (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                objective TEXT NOT NULL,
                constraints_text TEXT NOT NULL,
                rationale TEXT NOT NULL,
                linked_symbol TEXT
            );

            CREATE TABLE IF NOT EXISTS energy_runs (
                id INTEGER PRIMARY KEY,
                run_id TEXT UNIQUE NOT NULL,
                command TEXT NOT NULL,
                duration_s REAL NOT NULL,
                estimated_wh REAL NOT NULL,
                estimated_co2_kg REAL NOT NULL,
                status TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_symbol_module ON nodes(symbol, module);
            CREATE INDEX IF NOT EXISTS idx_edges_source_target ON edges(source, target);
            CREATE INDEX IF NOT EXISTS idx_findings_severity_rule ON findings(severity, rule_id);
            CREATE INDEX IF NOT EXISTS idx_intent_source ON intent_records(source);
            """
        )
        self.conn.commit()

    def clear_index(self) -> None:
        self.conn.execute("DELETE FROM artifacts")
        self.conn.execute("DELETE FROM nodes")
        self.conn.execute("DELETE FROM edges")
        self.conn.commit()

    def upsert_artifacts(self, artifacts: Iterable[Artifact]) -> None:
        self.conn.executemany(
            """
            INSERT INTO artifacts(path, hash, parse_ok, error)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                hash=excluded.hash,
                parse_ok=excluded.parse_ok,
                error=excluded.error
            """,
            [(a.path, a.hash, int(a.parse_ok), a.error) for a in artifacts],
        )
        self.conn.commit()

    def replace_nodes_edges(self, nodes: Iterable[DataNode], edges: Iterable[TransformEdge]) -> None:
        self.conn.execute("DELETE FROM nodes")
        self.conn.execute("DELETE FROM edges")
        self.conn.executemany(
            "INSERT INTO nodes(symbol, module, kind, location) VALUES (?, ?, ?, ?)",
            [(n.symbol, n.module, n.kind, n.location) for n in nodes],
        )
        self.conn.executemany(
            """
            INSERT INTO edges(source, target, transform_symbol, transform_kind, location, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (e.source, e.target, e.transform_symbol, e.transform_kind, e.location, e.confidence)
                for e in edges
            ],
        )
        self.conn.commit()

    def insert_findings(self, findings: Iterable[Finding]) -> None:
        self.conn.executemany(
            """
            INSERT INTO findings(rule_id, severity, file_path, line, message, autofix_applied)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (f.rule_id, f.severity, f.file_path, f.line, f.message, int(f.autofix_applied))
                for f in findings
            ],
        )
        self.conn.commit()

    def clear_findings(self) -> None:
        self.conn.execute("DELETE FROM findings")
        self.conn.commit()

    def insert_intent_records(self, records: Iterable[IntentRecord]) -> None:
        self.conn.executemany(
            """
            INSERT INTO intent_records(source, objective, constraints_text, rationale, linked_symbol)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(r.source, r.objective, r.constraints, r.rationale, r.linked_symbol) for r in records],
        )
        self.conn.commit()

    def query_lineage(self, symbol: str, depth: int = 3) -> dict:
        cur = self.conn.execute(
            "SELECT source, target, transform_symbol, transform_kind, location FROM edges WHERE source = ? OR target = ?",
            (symbol, symbol),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return {"symbol": symbol, "depth": depth, "edges": rows[:500]}

    def query_impact(self, file_or_symbol: str) -> dict:
        nodes = self.conn.execute(
            "SELECT symbol, module, location FROM nodes WHERE symbol = ? OR location LIKE ?",
            (file_or_symbol, f"%{file_or_symbol}%"),
        ).fetchall()
        out = []
        for n in nodes:
            edges = self.conn.execute(
                "SELECT source, target, transform_symbol FROM edges WHERE source = ? OR target = ?",
                (n["symbol"], n["symbol"]),
            ).fetchall()
            out.append({"node": dict(n), "connected_edges": [dict(e) for e in edges]})
        return {"query": file_or_symbol, "impacts": out}

    def get_dead_paths(self) -> dict:
        cur = self.conn.execute(
            """
            SELECT n.symbol, n.module, n.location
            FROM nodes n
            LEFT JOIN edges e1 ON e1.source = n.symbol
            LEFT JOIN edges e2 ON e2.target = n.symbol
            WHERE e1.id IS NULL AND e2.id IS NULL
            LIMIT 200
            """
        )
        return {"dead_nodes": [dict(r) for r in cur.fetchall()]}

    def get_intent_history(self, symbol_or_area: str) -> dict:
        cur = self.conn.execute(
            """
            SELECT source, objective, constraints_text, rationale, linked_symbol
            FROM intent_records
            WHERE linked_symbol = ? OR objective LIKE ? OR rationale LIKE ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (symbol_or_area, f"%{symbol_or_area}%", f"%{symbol_or_area}%"),
        )
        return {"query": symbol_or_area, "records": [dict(r) for r in cur.fetchall()]}

    def insert_energy_run(self, run: EnergyRun) -> None:
        self.conn.execute(
            """
            INSERT INTO energy_runs(run_id, command, duration_s, estimated_wh, estimated_co2_kg, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                command=excluded.command,
                duration_s=excluded.duration_s,
                estimated_wh=excluded.estimated_wh,
                estimated_co2_kg=excluded.estimated_co2_kg,
                status=excluded.status
            """,
            (
                run.run_id,
                run.command,
                run.duration_s,
                run.estimated_wh,
                run.estimated_co2_kg,
                run.status,
            ),
        )
        self.conn.commit()

    def get_energy_run(self, run_id: str) -> dict:
        row = self.conn.execute(
            "SELECT run_id, command, duration_s, estimated_wh, estimated_co2_kg, status FROM energy_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row else {}
