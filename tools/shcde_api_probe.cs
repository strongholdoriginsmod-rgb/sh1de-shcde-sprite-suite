// Offline metadata explorer for installed SHCDESE/APIShared assemblies.
// Never loads managed game code or invokes a game function.
using System;
using System.Collections.Generic;
using System.Linq;
using Mono.Cecil;

internal static class SpriteSuiteApiProbe
{
    private static string Clean(string text)
    {
        return (text ?? "").Replace('\t', ' ').Replace('\r', ' ')
                           .Replace('\n', ' ');
    }

    private static IEnumerable<TypeDefinition> Types(IEnumerable<TypeDefinition> types)
    {
        foreach (var type in types)
        {
            yield return type;
            foreach (var nested in Types(type.NestedTypes))
                yield return nested;
        }
    }

    private static void Main(string[] args)
    {
        if (args.Length < 1) throw new ArgumentException("Assembly path required");
        foreach (string path in args)
        {
            using (var assembly = AssemblyDefinition.ReadAssembly(path))
            {
                string identity = assembly.Name.FullName;
                Console.WriteLine("A\t" + Clean(identity) + "\t" + Clean(path));
                foreach (var type in Types(assembly.MainModule.Types))
                {
                    if (type.Name == "<Module>") continue;
                    string name = Clean(type.FullName);
                    Console.WriteLine("T\t" + Clean(identity) + "\t" + name
                                      + "\t" + (type.IsPublic || type.IsNestedPublic ? "public" : "other"));
                    foreach (var field in type.Fields)
                    {
                        Console.WriteLine("F\t" + Clean(identity) + "\t" + name
                            + "\t" + Clean(field.Name) + "\t" + Clean(field.FieldType.FullName)
                            + "\t" + (field.IsPublic ? "public" : "other"));
                    }
                    foreach (var method in type.Methods)
                    {
                        string parameters = string.Join(",", method.Parameters
                            .Select(p => Clean(p.ParameterType.FullName) + " " + Clean(p.Name)).ToArray());
                        Console.WriteLine("M\t" + Clean(identity) + "\t" + name
                            + "\t" + Clean(method.Name) + "\t" + Clean(method.ReturnType.FullName)
                            + "\t" + parameters + "\t" + (method.IsPublic ? "public" : "other"));
                    }
                }
            }
        }
    }
}
