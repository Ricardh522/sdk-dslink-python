import dslink


class LargeNodeStructure(dslink.DSLink):
    def start(self):
        for x in range(0, 9):
            first = dslink.Node("Test%i" % x, self.super_root)
            for y in range(0, 10):
                second = dslink.Node("Test%i" % y, first)
                first.add_child(second)
            self.super_root.add_child(first)

if __name__ == "__main__":
    LargeNodeStructure(dslink.Configuration("python-large", responder=True, requester=True, no_save_nodes=True))
