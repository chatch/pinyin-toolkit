from sqlalchemy.test.testing import assert_raises
from sqlalchemy.test.testing import assert_raises_message
from sqlalchemy.test.testing import emits_warning

import pickle
from sqlalchemy import Integer, String, UniqueConstraint, \
    CheckConstraint, ForeignKey, MetaData, Sequence, \
    ForeignKeyConstraint, ColumnDefault, Index
from sqlalchemy.test.schema import Table, Column
from sqlalchemy import schema, exc
import sqlalchemy as tsa
from sqlalchemy.test import TestBase, ComparesTables, \
    AssertsCompiledSQL, testing, engines
from sqlalchemy.test.testing import eq_

class MetaDataTest(TestBase, ComparesTables):
    def test_metadata_connect(self):
        metadata = MetaData()
        t1 = Table('table1', metadata, 
            Column('col1', Integer, primary_key=True),
            Column('col2', String(20)))
        metadata.bind = testing.db
        metadata.create_all()
        try:
            assert t1.count().scalar() == 0
        finally:
            metadata.drop_all()

    def test_metadata_contains(self):
        metadata = MetaData()
        t1 = Table('t1', metadata, Column('x', Integer))
        t2 = Table('t2', metadata, Column('x', Integer), schema='foo')
        t3 = Table('t2', MetaData(), Column('x', Integer))
        t4 = Table('t1', MetaData(), Column('x', Integer), schema='foo')

        assert "t1" in metadata
        assert "foo.t2" in metadata
        assert "t2" not in metadata
        assert "foo.t1" not in metadata
        assert t1 in metadata
        assert t2 in metadata
        assert t3 not in metadata
        assert t4 not in metadata

    def test_uninitialized_column_copy(self):
        for col in [
            Column('foo', String(), nullable=False),
            Column('baz', String(), unique=True),
            Column(Integer(), primary_key=True),
            Column('bar', Integer(), Sequence('foo_seq'), primary_key=True,
                                                            key='bar'),
            Column(Integer(), ForeignKey('bat.blah'), doc="this is a col"),
            Column('bar', Integer(), ForeignKey('bat.blah'), primary_key=True,
                                                            key='bar'),
            Column('bar', Integer(), info={'foo':'bar'}),
        ]:
            c2 = col.copy()
            for attr in ('name', 'type', 'nullable', 
                        'primary_key', 'key', 'unique', 'info',
                        'doc'):
                eq_(getattr(col, attr), getattr(c2, attr))
            eq_(len(col.foreign_keys), len(c2.foreign_keys))
            if col.default:
                eq_(c2.default.name, 'foo_seq')
            for a1, a2 in zip(col.foreign_keys, c2.foreign_keys):
                assert a1 is not a2
                eq_(a2._colspec, 'bat.blah')

    def test_uninitialized_column_copy_events(self):
        msgs = []
        def write(t, c):
            msgs.append("attach %s.%s" % (t.name, c.name))
        c1 = Column('foo', String())
        c1._on_table_attach(write)
        m = MetaData()
        for i in xrange(3):
            cx = c1.copy()
            t = Table('foo%d' % i, m, cx)
        eq_(msgs, ['attach foo0.foo', 'attach foo1.foo', 'attach foo2.foo'])


    def test_dupe_tables(self):
        metadata = MetaData()
        t1 = Table('table1', metadata, 
            Column('col1', Integer, primary_key=True),
            Column('col2', String(20)))

        metadata.bind = testing.db
        metadata.create_all()
        try:
            try:
                t1 = Table('table1', metadata, autoload=True)
                t2 = Table('table1', metadata, 
                    Column('col1', Integer, primary_key=True),
                    Column('col2', String(20)))
                assert False
            except tsa.exc.InvalidRequestError, e:
                assert str(e) \
                    == "Table 'table1' is already defined for this "\
                    "MetaData instance.  Specify 'useexisting=True' "\
                    "to redefine options and columns on an existing "\
                    "Table object."
        finally:
            metadata.drop_all()

    def test_fk_copy(self):
        c1 = Column('foo', Integer)
        c2 = Column('bar', Integer)
        m = MetaData()
        t1 = Table('t', m, c1, c2)

        kw = dict(onupdate="X", 
                        ondelete="Y", use_alter=True, name='f1',
                        deferrable="Z", initially="Q", link_to_name=True)

        fk1 = ForeignKey(c1, **kw) 
        fk2 = ForeignKeyConstraint((c1,), (c2,), **kw)

        t1.append_constraint(fk2)
        fk1c = fk1.copy()
        fk2c = fk2.copy()

        for k in kw:
            eq_(getattr(fk1c, k), kw[k])
            eq_(getattr(fk2c, k), kw[k])

    def test_check_constraint_copy(self):
        r = lambda x: x
        c = CheckConstraint("foo bar", 
                            name='name', 
                            initially=True, 
                            deferrable=True, 
                            _create_rule = r)
        c2 = c.copy()
        eq_(c2.name, 'name')
        eq_(str(c2.sqltext), "foo bar")
        eq_(c2.initially, True)
        eq_(c2.deferrable, True)
        assert c2._create_rule is r

    def test_fk_construct(self):
        c1 = Column('foo', Integer)
        c2 = Column('bar', Integer)
        m = MetaData()
        t1 = Table('t', m, c1, c2)
        fk1 = ForeignKeyConstraint(('foo', ), ('bar', ), table=t1)
        assert fk1 in t1.constraints

    def test_fk_no_such_parent_col_error(self):
        meta = MetaData()
        a = Table('a', meta, Column('a', Integer))
        b = Table('b', meta, Column('b', Integer))

        def go():
            a.append_constraint(
                ForeignKeyConstraint(['x'], ['b.b'])
            )
        assert_raises_message(
            exc.ArgumentError,
            "Can't create ForeignKeyConstraint on "
            "table 'a': no column named 'x' is present.",
            go
        )

    def test_fk_no_such_target_col_error(self):
        meta = MetaData()
        a = Table('a', meta, Column('a', Integer))
        b = Table('b', meta, Column('b', Integer))
        a.append_constraint(
            ForeignKeyConstraint(['a'], ['b.x'])
        )

        def go():
            list(a.c.a.foreign_keys)[0].column
        assert_raises_message(
            exc.NoReferencedColumnError,
            "Could not create ForeignKey 'b.x' on "
            "table 'a': table 'b' has no column named 'x'",
            go
        )

    @testing.exclude('mysql', '<', (4, 1, 1), 'early types are squirrely')
    def test_to_metadata(self):
        meta = MetaData()

        table = Table('mytable', meta,
            Column('myid', Integer, Sequence('foo_id_seq'), primary_key=True),
            Column('name', String(40), nullable=True),
            Column('foo', String(40), nullable=False, server_default='x',
                                                        server_onupdate='q'),
            Column('bar', String(40), nullable=False, default='y',
                                                        onupdate='z'),
            Column('description', String(30),
                                    CheckConstraint("description='hi'")),
            UniqueConstraint('name'),
            test_needs_fk=True,
        )

        table2 = Table('othertable', meta,
            Column('id', Integer, Sequence('foo_seq'), primary_key=True),
            Column('myid', Integer, 
                        ForeignKey('mytable.myid'),
                    ),
            test_needs_fk=True,
            )

        def test_to_metadata():
            meta2 = MetaData()
            table_c = table.tometadata(meta2)
            table2_c = table2.tometadata(meta2)
            return (table_c, table2_c)

        def test_pickle():
            meta.bind = testing.db
            meta2 = pickle.loads(pickle.dumps(meta))
            assert meta2.bind is None
            meta3 = pickle.loads(pickle.dumps(meta2))
            return (meta2.tables['mytable'], meta2.tables['othertable'])

        def test_pickle_via_reflect():
            # this is the most common use case, pickling the results of a
            # database reflection
            meta2 = MetaData(bind=testing.db)
            t1 = Table('mytable', meta2, autoload=True)
            t2 = Table('othertable', meta2, autoload=True)
            meta3 = pickle.loads(pickle.dumps(meta2))
            assert meta3.bind is None
            assert meta3.tables['mytable'] is not t1
            return (meta3.tables['mytable'], meta3.tables['othertable'])

        meta.create_all(testing.db)
        try:
            for test, has_constraints, reflect in (test_to_metadata,
                    True, False), (test_pickle, True, False), \
                (test_pickle_via_reflect, False, True):
                table_c, table2_c = test()
                self.assert_tables_equal(table, table_c)
                self.assert_tables_equal(table2, table2_c)
                assert table is not table_c
                assert table.primary_key is not table_c.primary_key
                assert list(table2_c.c.myid.foreign_keys)[0].column \
                    is table_c.c.myid
                assert list(table2_c.c.myid.foreign_keys)[0].column \
                    is not table.c.myid
                assert 'x' in str(table_c.c.foo.server_default.arg)
                if not reflect:
                    assert isinstance(table_c.c.myid.default, Sequence)
                    assert str(table_c.c.foo.server_onupdate.arg) == 'q'
                    assert str(table_c.c.bar.default.arg) == 'y'
                    assert getattr(table_c.c.bar.onupdate.arg, 'arg',
                                   table_c.c.bar.onupdate.arg) == 'z'
                    assert isinstance(table2_c.c.id.default, Sequence)

                # constraints dont get reflected for any dialect right
                # now

                if has_constraints:
                    for c in table_c.c.description.constraints:
                        if isinstance(c, CheckConstraint):
                            break
                    else:
                        assert False
                    assert str(c.sqltext) == "description='hi'"
                    for c in table_c.constraints:
                        if isinstance(c, UniqueConstraint):
                            break
                    else:
                        assert False
                    assert c.columns.contains_column(table_c.c.name)
                    assert not c.columns.contains_column(table.c.name)
        finally:
            meta.drop_all(testing.db)

    def test_tometadata_with_schema(self):
        meta = MetaData()

        table = Table('mytable', meta,
            Column('myid', Integer, primary_key=True),
            Column('name', String(40), nullable=True),
            Column('description', String(30),
                            CheckConstraint("description='hi'")),
            UniqueConstraint('name'),
            test_needs_fk=True,
        )

        table2 = Table('othertable', meta,
            Column('id', Integer, primary_key=True),
            Column('myid', Integer, ForeignKey('mytable.myid')),
            test_needs_fk=True,
            )

        meta2 = MetaData()
        table_c = table.tometadata(meta2, schema='someschema')
        table2_c = table2.tometadata(meta2, schema='someschema')

        eq_(str(table_c.join(table2_c).onclause), str(table_c.c.myid
            == table2_c.c.myid))
        eq_(str(table_c.join(table2_c).onclause),
            'someschema.mytable.myid = someschema.othertable.myid')

    def test_tometadata_kwargs(self):
        meta = MetaData()

        table = Table('mytable', meta,
            Column('myid', Integer, primary_key=True),
            mysql_engine='InnoDB',
        )

        meta2 = MetaData()
        table_c = table.tometadata(meta2)

        eq_(table.kwargs,table_c.kwargs)

    def test_tometadata_indexes(self):
        meta = MetaData()

        table = Table('mytable', meta,
            Column('id', Integer, primary_key=True),
            Column('data1', Integer, index=True),
            Column('data2', Integer),
        )
        Index('multi',table.c.data1,table.c.data2),

        meta2 = MetaData()
        table_c = table.tometadata(meta2)

        def _get_key(i):
            return [i.name,i.unique] + \
                    sorted(i.kwargs.items()) + \
                    i.columns.keys()

        eq_(
            sorted([_get_key(i) for i in table.indexes]),
            sorted([_get_key(i) for i in table_c.indexes])
        )

    @emits_warning("Table '.+' already exists within the given MetaData")
    def test_tometadata_already_there(self):

        meta1 = MetaData()
        table1 = Table('mytable', meta1,
            Column('myid', Integer, primary_key=True),
        )
        meta2 = MetaData()
        table2 = Table('mytable', meta2,
            Column('yourid', Integer, primary_key=True),
        )

        meta3 = MetaData()

        table_c = table1.tometadata(meta2)
        table_d = table2.tometadata(meta2)

        # d'oh!
        assert table_c is table_d

    def test_tometadata_default_schema(self):
        meta = MetaData()

        table = Table('mytable', meta,
            Column('myid', Integer, primary_key=True),
            Column('name', String(40), nullable=True),
            Column('description', String(30),
                        CheckConstraint("description='hi'")),
            UniqueConstraint('name'),
            test_needs_fk=True,
            schema='myschema',
        )

        table2 = Table('othertable', meta,
            Column('id', Integer, primary_key=True),
            Column('myid', Integer, ForeignKey('myschema.mytable.myid')),
            test_needs_fk=True,
            schema='myschema',
            )

        meta2 = MetaData()
        table_c = table.tometadata(meta2)
        table2_c = table2.tometadata(meta2)

        eq_(str(table_c.join(table2_c).onclause), str(table_c.c.myid
            == table2_c.c.myid))
        eq_(str(table_c.join(table2_c).onclause),
            'myschema.mytable.myid = myschema.othertable.myid')

    def test_manual_dependencies(self):
        meta = MetaData()
        a = Table('a', meta, Column('foo', Integer))
        b = Table('b', meta, Column('foo', Integer))
        c = Table('c', meta, Column('foo', Integer))
        d = Table('d', meta, Column('foo', Integer))
        e = Table('e', meta, Column('foo', Integer))

        e.add_is_dependent_on(c)
        a.add_is_dependent_on(b)
        b.add_is_dependent_on(d)
        e.add_is_dependent_on(b)
        c.add_is_dependent_on(a)
        eq_(
            meta.sorted_tables,
            [d, b, a, c, e]
        )


    def test_tometadata_strip_schema(self):
        meta = MetaData()

        table = Table('mytable', meta,
            Column('myid', Integer, primary_key=True),
            Column('name', String(40), nullable=True),
            Column('description', String(30),
                        CheckConstraint("description='hi'")),
            UniqueConstraint('name'),
            test_needs_fk=True,
        )

        table2 = Table('othertable', meta,
            Column('id', Integer, primary_key=True),
            Column('myid', Integer, ForeignKey('mytable.myid')),
            test_needs_fk=True,
            )

        meta2 = MetaData()
        table_c = table.tometadata(meta2, schema=None)
        table2_c = table2.tometadata(meta2, schema=None)

        eq_(str(table_c.join(table2_c).onclause), str(table_c.c.myid
            == table2_c.c.myid))
        eq_(str(table_c.join(table2_c).onclause),
            'mytable.myid = othertable.myid')

    def test_nonexistent(self):
        assert_raises(tsa.exc.NoSuchTableError, Table,
                          'fake_table',
                          MetaData(testing.db), autoload=True)

class ColumnDefaultsTest(TestBase):
    """test assignment of default fixtures to columns"""

    def _fixture(self, *arg, **kw):
        return Column('x', Integer, *arg, **kw)

    def test_server_default_positional(self):
        target = schema.DefaultClause('y')
        c = self._fixture(target)
        assert c.server_default is target
        assert target.column is c

    def test_server_default_keyword_as_schemaitem(self):
        target = schema.DefaultClause('y')
        c = self._fixture(server_default=target)
        assert c.server_default is target
        assert target.column is c

    def test_server_default_keyword_as_clause(self):
        target = 'y'
        c = self._fixture(server_default=target)
        assert c.server_default.arg == target
        assert c.server_default.column is c

    def test_server_default_onupdate_positional(self):
        target = schema.DefaultClause('y', for_update=True)
        c = self._fixture(target)
        assert c.server_onupdate is target
        assert target.column is c

    def test_server_default_onupdate_keyword_as_schemaitem(self):
        target = schema.DefaultClause('y', for_update=True)
        c = self._fixture(server_onupdate=target)
        assert c.server_onupdate is target
        assert target.column is c

    def test_server_default_onupdate_keyword_as_clause(self):
        target = 'y'
        c = self._fixture(server_onupdate=target)
        assert c.server_onupdate.arg == target
        assert c.server_onupdate.column is c

    def test_column_default_positional(self):
        target = schema.ColumnDefault('y')
        c = self._fixture(target)
        assert c.default is target
        assert target.column is c

    def test_column_default_keyword_as_schemaitem(self):
        target = schema.ColumnDefault('y')
        c = self._fixture(default=target)
        assert c.default is target
        assert target.column is c

    def test_column_default_keyword_as_clause(self):
        target = 'y'
        c = self._fixture(default=target)
        assert c.default.arg == target
        assert c.default.column is c

    def test_column_default_onupdate_positional(self):
        target = schema.ColumnDefault('y', for_update=True)
        c = self._fixture(target)
        assert c.onupdate is target
        assert target.column is c

    def test_column_default_onupdate_keyword_as_schemaitem(self):
        target = schema.ColumnDefault('y', for_update=True)
        c = self._fixture(onupdate=target)
        assert c.onupdate is target
        assert target.column is c

    def test_column_default_onupdate_keyword_as_clause(self):
        target = 'y'
        c = self._fixture(onupdate=target)
        assert c.onupdate.arg == target
        assert c.onupdate.column is c



class TableOptionsTest(TestBase, AssertsCompiledSQL):
    def test_prefixes(self):
        table1 = Table("temporary_table_1", MetaData(),
                      Column("col1", Integer),
                      prefixes = ["TEMPORARY"])

        self.assert_compile(
            schema.CreateTable(table1), 
            "CREATE TEMPORARY TABLE temporary_table_1 (col1 INTEGER)"
        )

        table2 = Table("temporary_table_2", MetaData(),
                      Column("col1", Integer),
                      prefixes = ["VIRTUAL"])
        self.assert_compile(
          schema.CreateTable(table2), 
          "CREATE VIRTUAL TABLE temporary_table_2 (col1 INTEGER)"
        )

    def test_table_info(self):
        metadata = MetaData()
        t1 = Table('foo', metadata, info={'x':'y'})
        t2 = Table('bar', metadata, info={})
        t3 = Table('bat', metadata)
        assert t1.info == {'x':'y'}
        assert t2.info == {}
        assert t3.info == {}
        for t in (t1, t2, t3):
            t.info['bar'] = 'zip'
            assert t.info['bar'] == 'zip'

