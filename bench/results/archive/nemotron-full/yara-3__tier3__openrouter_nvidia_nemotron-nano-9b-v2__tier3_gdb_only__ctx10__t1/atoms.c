          memcpy(&leaf->atom, &atom, sizeof(atom));
          memcpy(
              &leaf->re_nodes,
              &recent_re_nodes[shift],
              sizeof(recent_re_nodes) - shift * sizeof(recent_re_nodes[0]));
        }
        else
        {
          memcpy(&leaf->atom, &best_atom, sizeof(best_atom));
          memcpy(
              &leaf->re_nodes,
              &best_atom_re_nodes,
              sizeof(best_atom_re_nodes));
        }

        _yr_atoms_tree_node_append(current_appending_node, leaf);
        n = 0;
      }

      current_appending_node = si.new_appending_node;
    }

    if (si.re_node != NULL)
    {
      switch(si.re_node->type)
      {
        case RE_NODE_LITERAL:
        case RE_NODE_MASKED_LITERAL:
        case RE_NODE_ANY:

          if (n < YR_MAX_ATOM_LENGTH)
          {
            recent_re_nodes[n] = si.re_node;
            best_atom_re_nodes[n] = si.re_node;
            best_atom.bytes[n] = (uint8_t) si.re_node->value;
            best_atom.mask[n] = (uint8_t) si.re_node->mask;
            best_atom.length = ++n;
          }
          else if (best_quality < YR_MAX_ATOM_QUALITY)
          {
            make_atom_from_re_nodes(atom, n, recent_re_nodes);
            shift = _yr_atoms_trim(&atom);
            quality = config->get_atom_quality(config, &atom);

            if (quality > best_quality)
            {
              for (i = 0; i < atom.length; i++)
              {
                best_atom.bytes[i] = atom.bytes[i];
                best_atom.mask[i] = atom.mask[i];
                best_atom_re_nodes[i] = recent_re_nodes[i + shift];
              }

              best_quality = quality;
            }

            for (i = 1; i < YR_MAX_ATOM_LENGTH; i++)
              recent_re_nodes[i - 1] = recent_re_nodes[i];

            recent_re_nodes[YR_MAX_ATOM_LENGTH - 1] = si.re_node;
          }

          break;

        case RE_NODE_CONCAT:

          re_node = si.re_node->children_tail;

          // Push children right to left, they are poped left to right.
          while (re_node != NULL)
          {
            si.new_appending_node = NULL;
            si.re_node = re_node;

            FAIL_ON_ERROR_WITH_CLEANUP(
                yr_stack_push(stack, &si),
                yr_stack_destroy(stack));

            re_node = re_node->prev_sibling;
          }

          break;

        case RE_NODE_ALT:

          // Create ATOM_TREE_AND node with two ATOM_TREE_OR children nodes.
          and_node = _yr_atoms_tree_node_create(ATOM_TREE_AND);
          left_node = _yr_atoms_tree_node_create(ATOM_TREE_OR);
          right_node = _yr_atoms_tree_node_create(ATOM_TREE_OR);

          if (and_node == NULL || left_node == NULL || right_node == NULL)
          {
            _yr_atoms_tree_node_destroy(and_node);
            _yr_atoms_tree_node_destroy(left_node);
            _yr_atoms_tree_node_destroy(right_node);

            yr_stack_destroy(stack);

            return ERROR_INSUFFICIENT_MEMORY;
          }

