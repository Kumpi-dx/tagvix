import pymysql


def _safe_identifier(name):
    if not name or not name.replace("_", "").isalnum() or not name[0].isalpha():
        raise ValueError("Nama tabel tidak valid: " + str(name))
    return name


def _format_value(value):
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class MySQLStore:
    def __init__(self, host, port, user, password, database, charset="latin1",
                 table_reg="t_reg_status", table_transmit="t_transmit",
                 dev_name="OMRON", group_name="default",
                 autocreate=True, logger=None):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.database = database
        self.charset = charset
        self.table_reg = _safe_identifier(table_reg)
        self.table_transmit = _safe_identifier(table_transmit)
        self.dev_name = dev_name
        self.group_name = group_name
        self.autocreate = autocreate
        self.log = logger
        self._conn = None

    def connect(self):
        if self.autocreate:
            self._create_database()
        self._conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset=self.charset,
            autocommit=True,
            connect_timeout=5,
            read_timeout=5,
            write_timeout=5,
        )
        if self.autocreate:
            self._create_tables()

    def _create_database(self):
        conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            charset=self.charset,
            autocommit=True,
            connect_timeout=5,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE DATABASE IF NOT EXISTS `{}` CHARACTER SET {} "
                    "COLLATE {}_swedish_ci".format(
                        self.database, self.charset, self.charset
                    )
                )
        finally:
            conn.close()

    def _create_tables(self):
        reg_sql = """
            CREATE TABLE IF NOT EXISTS `{table}` (
                CLIENT_HDL INT(11) NOT NULL AUTO_INCREMENT,
                DEV_NAME VARCHAR(30) NOT NULL DEFAULT 'OMRON',
                GROUP_NAME VARCHAR(30) NOT NULL,
                TAG_NAME VARCHAR(50) NOT NULL DEFAULT '',
                REG_VALUE VARCHAR(50) DEFAULT NULL,
                TR_TIME DATETIME DEFAULT CURRENT_TIMESTAMP,
                CONNECT_STAT CHAR(1) DEFAULT '1',
                PRIMARY KEY (CLIENT_HDL) USING BTREE
            ) ENGINE=MyISAM DEFAULT CHARSET={charset}
        """.format(table=self.table_reg, charset=self.charset)

        transmit_sql = """
            CREATE TABLE IF NOT EXISTS `{table}` (
                DEV_NAME VARCHAR(100) DEFAULT NULL,
                REG_NAME VARCHAR(100) DEFAULT NULL,
                REG_VALUE VARCHAR(50) DEFAULT NULL,
                TTL SMALLINT(5) UNSIGNED DEFAULT NULL,
                TR_TIME DATETIME DEFAULT NULL
            ) ENGINE=MyISAM DEFAULT CHARSET={charset}
        """.format(table=self.table_transmit, charset=self.charset)

        with self._conn.cursor() as cur:
            cur.execute(reg_sql)
            cur.execute(transmit_sql)

    def _ensure_alive(self):
        try:
            self._conn.ping(reconnect=True)
        except Exception:
            self.close()
            self.connect()

    def save_readings(self, readings, ts):
        """Update (atau insert) nilai tag ke tabel status register."""
        if self._conn is None:
            self.connect()
        self._ensure_alive()

        select_sql = (
            "SELECT CLIENT_HDL FROM `{}` WHERE DEV_NAME=%s AND GROUP_NAME=%s "
            "AND TAG_NAME=%s LIMIT 1".format(self.table_reg)
        )
        update_sql = (
            "UPDATE `{}` SET REG_VALUE=%s, TR_TIME=%s, CONNECT_STAT=%s "
            "WHERE CLIENT_HDL=%s".format(self.table_reg)
        )
        insert_sql = (
            "INSERT INTO `{}` (DEV_NAME, GROUP_NAME, TAG_NAME, REG_VALUE, TR_TIME, "
            "CONNECT_STAT) VALUES (%s, %s, %s, %s, %s, %s)".format(self.table_reg)
        )

        with self._conn.cursor() as cur:
            for r in readings:
                tag_name = r.address
                value = _format_value(r.value)
                stat = "1" if r.quality == "GOOD" else "0"
                cur.execute(select_sql, (self.dev_name, self.group_name, tag_name))
                row = cur.fetchone()
                if row:
                    cur.execute(update_sql, (value, ts, stat, row[0]))
                else:
                    cur.execute(insert_sql, (self.dev_name, self.group_name,
                                             tag_name, value, ts, stat))

    def fetch_transmit(self):
        """Ambil baris perintah tulis (semua kolom) dari tabel transmit."""
        if self._conn is None:
            self.connect()
        self._ensure_alive()
        sql = (
            "SELECT DEV_NAME, REG_NAME, REG_VALUE, TTL, TR_TIME "
            "FROM `{}`".format(self.table_transmit)
        )
        with self._conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    def delete_transmit(self, row):
        """Hapus satu baris transmit yang sudah dieksekusi.

        Tabel transmit tidak punya primary key, jadi baris dihapus dengan
        mencocokkan seluruh kolomnya (NULL-safe) dan LIMIT 1.
        """
        if self._conn is None:
            self.connect()
        self._ensure_alive()
        dev_name, reg_name, reg_value, ttl, tr_time = row
        sql = (
            "DELETE FROM `{t}` WHERE DEV_NAME<=>%s AND REG_NAME<=>%s "
            "AND REG_VALUE<=>%s AND TTL<=>%s AND TR_TIME<=>%s LIMIT 1"
        ).format(t=self.table_transmit)
        with self._conn.cursor() as cur:
            cur.execute(sql, (dev_name, reg_name, reg_value, ttl, tr_time))
            return cur.rowcount

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
