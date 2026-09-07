use super::*;

struct Descriptor(Arc<AtomicBool>);
impl Write for Descriptor {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
impl Drop for Descriptor {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

#[derive(Debug, Clone)]
struct DescriptorDependentChild {
    closed: Arc<AtomicBool>,
    observed_closed_at_wait: Arc<AtomicBool>,
}
impl portable_pty::ChildKiller for DescriptorDependentChild {
    fn kill(&mut self) -> io::Result<()> {
        Ok(())
    }
    fn clone_killer(&self) -> Box<dyn portable_pty::ChildKiller + Send + Sync> {
        Box::new(self.clone())
    }
}
impl Child for DescriptorDependentChild {
    fn try_wait(&mut self) -> io::Result<Option<portable_pty::ExitStatus>> {
        Ok(None)
    }
    fn wait(&mut self) -> io::Result<portable_pty::ExitStatus> {
        // A real PTY child may wait for terminal teardown here. Record the
        // ordering without hanging the test process on a regression.
        self.observed_closed_at_wait
            .store(self.closed.load(Ordering::Acquire), Ordering::Release);
        Ok(portable_pty::ExitStatus::with_exit_code(0))
    }
    fn process_id(&self) -> Option<u32> {
        None
    }
}

#[test]
fn releases_terminal_descriptors_before_waiting_for_child_exit() {
    let closed = Arc::new(AtomicBool::new(false));
    let observed = Arc::new(AtomicBool::new(false));
    let mut resources = Resources {
        child: Some(Box::new(DescriptorDependentChild {
            closed: Arc::clone(&closed),
            observed_closed_at_wait: Arc::clone(&observed),
        })),
        master: None,
        reader: None,
        writer: Some(Box::new(Descriptor(Arc::clone(&closed)))),
    };
    resources.close().expect("cleanup");
    assert!(observed.load(Ordering::Acquire));
    assert!(resources.child.is_none());
}
